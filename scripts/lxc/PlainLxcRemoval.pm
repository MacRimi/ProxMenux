# Run Proxmox's own LXC DELETE worker with a reviewed-target guard.
package PlainLxcRemoval;

use strict;
use warnings;
use Digest::SHA qw(sha256_hex);
use Fcntl qw(O_CREAT O_EXCL O_WRONLY);
use JSON::PP qw(decode_json);

our @ISA = ('PVE::RPCEnvironment');
our $CFS_ROOT = '/etc/pve';
our $RECEIPT_ROOT = '/run/proxmenux-lxc-removals';

sub read_bytes {
    my ($fh) = @_;
    local $/;
    return scalar <$fh> // '';
}

sub read_json {
    my ($path) = @_;
    open(my $fh, '<:raw', $path) or die "Proxmox identity unavailable\n";
    return decode_json(read_bytes($fh));
}

sub check_identity {
    my ($guard, $node, $vmid) = @_;
    my $start = read_json("$CFS_ROOT/.version")->{starttime};
    my $guest = read_json("$CFS_ROOT/.vmlist")->{ids}->{$vmid} // {};
    die "Reviewed LXC identity changed\n" unless ($guest->{node} // '') eq $node
        && ($guest->{type} // '') eq 'lxc'
        && defined($start) && $start eq $guard->{generation}->[0]
        && defined($guest->{version}) && $guest->{version} eq $guard->{generation}->[1];
    my $path = PVE::LXC::Config->config_file($vmid);
    open(my $fh, '<:raw', $path) or die "Reviewed LXC configuration unavailable\n";
    my @file = stat($fh);
    my $raw = read_bytes($fh);
    die "Reviewed LXC configuration changed\n" unless @file
        && join(':', @file[0, 1, 9, 10]) eq join(':', @{$guard->{file}})
        && sha256_hex($raw) eq $guard->{digest};
}

sub check_disk {
    my ($vmid, $expected) = @_;
    my $config = PVE::LXC::Config->load_config($vmid);
    die "Target is a container template\n" if $config->{template};
    my $root = PVE::LXC::Config->parse_volume('rootfs', $config->{rootfs});
    die "Reviewed root volume changed\n" unless $root && $root->{volume} eq $expected;
    die "Reviewed root volume unavailable\n" unless root_volume_exists($vmid, $expected);
}

sub root_volume_exists {
    my ($vmid, $expected) = @_;
    die "Invalid reviewed volume request\n" unless ($vmid // '') =~ /\A[1-9][0-9]{2,8}\z/
        && ($expected // '') =~ m{\A[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.+:/@-]*\z};
    require PVE::Storage;
    my $storage = PVE::Storage::config();
    my ($sid) = PVE::Storage::parse_volume_id($expected);
    my $content = PVE::Storage::storage_config($storage, $sid)->{content};
    die "Reviewed storage no longer supports guest disks\n" unless $content->{rootdir} || $content->{images};
    my (undef, undef, $owner, undef, undef, $base) = PVE::Storage::parse_volname($storage, $expected);
    die "Reviewed root volume has no unambiguous owner\n"
        unless defined($owner) && $owner == $vmid && !$base;
    # An orphaned LXC disk may no longer be classified as rootdir once its
    # config is gone. Query the exact volume via the native disk inventory.
    my $volumes = PVE::Storage::vdisk_list($storage, $sid, $vmid)->{$sid};
    die "Reviewed root volume inventory unavailable\n" unless ref($volumes) eq 'ARRAY'
        && !grep { ref($_) ne 'HASH' || !defined($_->{volid}) } @$volumes;
    my @matches = grep { $_->{volid} eq $expected } @$volumes;
    return 0 unless @matches;
    die "Reviewed root volume inventory is ambiguous\n"
        unless @matches == 1 && ($matches[0]->{vmid} // -1) == $vmid;
    return 1;
}

sub publish_task {
    my ($operation, $upid) = @_;
    my $dir = "$RECEIPT_ROOT/$operation";
    my $staging = "$dir/worker-$$";
    sysopen(my $fh, $staging, O_WRONLY | O_CREAT | O_EXCL, 0600)
        or die "Cannot stage removal receipt\n";
    my $written = print {$fh} "$upid\n";
    my $closed = close($fh);
    my $claimed = $written && $closed && link($staging, "$dir/result");
    unlink($staging);
    die "Removal receipt was not claimed; no removal was started\n" unless $claimed;
}

sub valid_target {
    my ($vmid, $guard) = @_;
    return !ref($vmid) && ($vmid // '') =~ /\A[1-9][0-9]{2,8}\z/
        && ref($guard) eq 'HASH' && join(',', sort keys %$guard) eq 'digest,file,generation'
        && ($guard->{digest} // '') =~ /\A[0-9a-f]{64}\z/
        && ref($guard->{generation}) eq 'ARRAY' && @{$guard->{generation}} == 2
        && ref($guard->{file}) eq 'ARRAY' && @{$guard->{file}} == 4
        && !grep { !defined($_) || ref($_) || !/\A[0-9]{1,20}\z/ }
            (@{$guard->{generation}}, @{$guard->{file}});
}

sub disable_protection {
    my ($node, $params, $set_option) = @_;
    my ($vmid, $guard) = @$params{qw(vmid guard)};
    die "Invalid protection request\n"
        unless join(',', sort keys %$params) eq 'guard,vmid' && valid_target($vmid, $guard);
    require PVE::LXC::Config;
    require PVE::LXC;
    return PVE::LXC::Config->lock_config($vmid, sub {
        check_identity($guard, $node, $vmid);
        my $config = PVE::LXC::Config->load_config($vmid);
        die "Container is running\n" if PVE::LXC::check_running($vmid);
        die "Removal protection is not enabled\n" unless $config->{protection};
        $set_option->($vmid, $config->{digest});
        die "Protection change not confirmed\n" if PVE::LXC::Config->load_config($vmid)->{protection};
        return 1;
    });
}

sub prepare {
    my ($self, $node, $params) = @_;
    my ($vmid, $operation, $guard, $volume, $purge, $destroy_unreferenced) =
        @$params{qw(vmid operation guard volume purge destroy_unreferenced_disks)};
    die "Invalid removal request\n" unless join(',', sort keys %$params)
            eq 'destroy_unreferenced_disks,guard,operation,purge,vmid,volume'
        && !ref($purge) && ($purge // '') =~ /\A[01]\z/
        && !ref($destroy_unreferenced) && ($destroy_unreferenced // '') =~ /\A[01]\z/
        && valid_target($vmid, $guard)
        && ($operation // '') =~ /\A[0-9a-f]{32}\z/
        && ($volume // '') =~ m{\A[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.+:/@-]*\z};
    require PVE::LXC::Config;
    require PVE::Storage;
    check_identity($guard, $node, $vmid);
    $self->{plain_lxc_removal} = [$vmid, $node, $operation, $guard, $volume];
    return { purge => 0 + $purge, 'destroy-unreferenced-disks' => 0 + $destroy_unreferenced };
}

sub fork_worker {
    my ($self, $type, $id, $user, $worker, @rest) = @_;
    if ($self->{plain_lxc_native_worker}) {
        return $self->SUPER::fork_worker($type, $id, $user, $worker, @rest);
    }
    my ($vmid, $node, $operation, $guard, $volume) = @{$self->{plain_lxc_removal}};
    die "Unexpected removal worker\n" unless $type eq 'vzdestroy' && $id eq $vmid && $user eq 'root@pam';
    return $self->SUPER::fork_worker($type, $id, $user, sub {
        my ($upid) = @_;
        die "Unexpected removal task\n"
            unless $upid =~ /\AUPID:\Q$node\E:[0-9A-Fa-f]{8}:[0-9A-Fa-f]{8,9}:[0-9A-Fa-f]{8}:vzdestroy:\Q$vmid\E:root\@pam:\z/;
        publish_task($operation, $upid);
        # PVE's own worker reacquires this lock in the same process. Its lock
        # helper is reentrant, so the identity and disk checks stay protected
        # until the native worker has finished.
        PVE::LXC::Config->lock_config($vmid, sub {
            check_identity($guard, $node, $vmid);
            check_disk($vmid, $volume);
            # Storage plugins may start their own cleanup worker (imgdel).
            local $self->{plain_lxc_native_worker} = 1;
            $worker->($upid);
        });
    }, @rest);
}

1;
