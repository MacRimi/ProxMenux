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
    my $storage = PVE::Storage::config();
    my ($sid) = PVE::Storage::parse_volume_id($expected);
    my (undef, undef, $owner, undef, undef, $base) = PVE::Storage::parse_volname($storage, $expected);
    die "Reviewed root volume has no unambiguous owner\n"
        unless defined($owner) && $owner == $vmid && !$base;
    my $volumes = PVE::Storage::volume_list($storage, $sid, $vmid, undef);
    die "Reviewed root volume unavailable\n"
        unless grep { ($_->{volid} // '') eq $expected && ($_->{vmid} // -1) == $vmid } @$volumes;
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

sub prepare {
    my ($self, $node, $params) = @_;
    my ($vmid, $operation, $guard, $volume) = @$params{qw(vmid operation guard volume)};
    die "Invalid removal request\n" unless join(',', sort keys %$params) eq 'guard,operation,vmid,volume'
        && ($vmid // '') =~ /\A[1-9][0-9]{2,8}\z/
        && ($operation // '') =~ /\A[0-9a-f]{32}\z/
        && ($volume // '') =~ m{\A[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.+:/@-]*\z}
        && ref($guard) eq 'HASH' && join(',', sort keys %$guard) eq 'digest,file,generation'
        && ($guard->{digest} // '') =~ /\A[0-9a-f]{64}\z/
        && ref($guard->{generation}) eq 'ARRAY' && @{$guard->{generation}} == 2
        && ref($guard->{file}) eq 'ARRAY' && @{$guard->{file}} == 4
        && !grep { !defined($_) || ref($_) || !/\A[0-9]{1,20}\z/ }
            (@{$guard->{generation}}, @{$guard->{file}});
    require PVE::LXC::Config;
    require PVE::Storage;
    check_identity($guard, $node, $vmid);
    $self->{plain_lxc_removal} = [$vmid, $node, $operation, $guard, $volume];
    return;
}

sub fork_worker {
    my ($self, $type, $id, $user, $worker, @rest) = @_;
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
            $worker->($upid);
        });
    }, @rest);
}

1;
