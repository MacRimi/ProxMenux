# Simulate the Proxmox wrapper's parent API and its deferred child worker.
use strict;
use warnings;
use JSON::PP qw(decode_json encode_json);

our ($request, $deferred, $under_lock, $native_calls, $nested_calls) = (undef, undef, 0, 0, 0);
{
    package PVE::RPCEnvironment;
    sub fork_worker {
        my ($self, $type, $vmid, $user, $callback) = @_;
        if ($type eq 'imgdel') {
            die unless $main::under_lock && !defined($vmid) && $user eq 'root@pam';
            ++$main::nested_calls;
            return 'fixture-imgdel';
        }
        die unless $type eq 'vzdestroy' && $vmid == 100 && $user eq 'root@pam';
        $main::deferred = $callback;
        return $main::request->{task};
    }
    package PVE::LXC::Config;
    sub config_file { return $main::request->{config}; }
    sub load_config {
        die "configuration load must hold native lock" unless $main::under_lock;
        return { rootfs => $main::request->{args}->{volume},
                 template => $main::request->{scenario} eq 'template_changed' ? 1 : 0 };
    }
    sub parse_volume { return { volume => $_[2] }; }
    sub lock_config {
        local $main::under_lock = 1;
        return $_[2]->();
    }
    package PVE::Storage;
    sub config { return {}; }
    sub storage_config {
        return {content => $main::request->{scenario} eq 'storage_changed' ? {} : {rootdir => 1}};
    }
    sub parse_volume_id { return split(':', $_[0], 2); }
    sub parse_volname {
        return ('rootdir', 'disk', $main::request->{scenario} eq 'foreign_disk' ? 200 : 100);
    }
    sub vdisk_list {
        my (undef, $sid, $vmid, @extra) = @_;
        die "query only the reviewed storage and VMID independently of the disk class"
            unless $sid eq 'local-lvm' && $vmid == 100 && !@extra;
        return { $sid => [{ volid => $main::request->{args}->{volume}, vmid => 100, content => 'images' }] };
    }
}
$INC{'PVE/LXC/Config.pm'} = 1;
$INC{'PVE/Storage.pm'} = 1;
require $ARGV[0];
{
    local $/;
    $request = decode_json(<STDIN>);
}
{
    no warnings 'once';
    $PlainLxcRemoval::CFS_ROOT = $request->{cfs};
    $PlainLxcRemoval::RECEIPT_ROOT = $request->{receipts};
}
my $rpc = bless {}, 'PlainLxcRemoval';
my $options = $rpc->prepare('fixture', $request->{args});
my $unreviewed_worker = eval { $rpc->fork_worker('imgdel', undef, 'root@pam', sub {}); 1 };
die "unreviewed storage worker was allowed" if $unreviewed_worker;
my $operation = $request->{args}->{operation};
my $native = sub {
    # The worker must be tied to a receipt, under the same lock from which
    # native Proxmox re-enters the configuration lock.
    die unless $under_lock && $_[0] eq $request->{task};
    open(my $receipt, '<', "$request->{receipts}/$operation/result") or die;
    die unless <$receipt> eq "$request->{task}\n";
    die unless $rpc->fork_worker('imgdel', undef, 'root@pam', sub {}) eq 'fixture-imgdel';
    ++$native_calls;
};
my $returned_upid = $rpc->fork_worker('vzdestroy', 100, 'root@pam', $native);
my $before_worker = $native_calls;
if ($request->{scenario} eq 'generation_changed') {
    open(my $vmlist, '>', "$request->{cfs}/.vmlist") or die;
    print {$vmlist} encode_json({ ids => { 100 => { node => 'fixture', type => 'lxc', version => 5 } } });
    close($vmlist) or die;
}
my $ok = eval { $deferred->($request->{task}); 1 };
die "fake worker failed unexpectedly: $@" if !$ok && $request->{scenario} eq 'success';
print encode_json({ returned_upid => $returned_upid, before_worker => $before_worker,
    native_calls => $native_calls, nested_calls => $nested_calls, options => $options });
