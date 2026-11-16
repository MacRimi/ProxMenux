#!/usr/bin/perl

# ==========================================================
# ProxMenux - Plain LXC console creation
# ==========================================================
# Author      : Vaso73
# GitHub      : github.com/Vaso73
# Maintainer  : MacRimi
# Copyright   : (c) 2026 MacRimi & contributors
# License     : (GPL-3.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.0
# Last Updated: 15/11/2026
# ==========================================================
# Description:
# Native PVE adapter for plain LXC inventory and confirmed creation,
# first-boot preparation and optional start on the local node.
# ==========================================================
# Dispatch the native local PVE handlers with JSON on stdin. In particular,
# neither a process argument nor an environment variable carries the password.
use strict;
use warnings;
use Fcntl qw(F_SETFD FD_CLOEXEC S_ISLNK S_ISDIR S_ISCHR);
use JSON::PP qw(decode_json encode_json);
use POSIX qw(dup dup2);
use File::Basename;

umask 0022; # Native extraction must be able to traverse the new rootfs.
open(my $null, '>', '/dev/null') or exit 1;
my $response_fd = dup(1);
open(my $response, '>&=', $response_fd) or exit 1;
fcntl($response, F_SETFD, FD_CLOEXEC) or exit 1;
dup2(fileno($null), 1);
dup2(fileno($null), 2);

sub handle {
    my ($method, $path, $params) = @_;
    my $uri = {};
    my ($handler, $info) = PVE::API2->find_handler($method, $path, $uri);
    die unless $handler && $info;
    return $handler->handle($info, { %$params, %$uri });
}

sub safe_mount_path {
    my ($path, $host) = @_;
    die unless defined($path) && !ref($path) && length($path) <= 255
        && $path =~ m{\A/[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*\z}
        && $path !~ m{(?:\A|/)\.\.?(?:/|\z)};
    my @protected = qw(/etc /proc /sys /dev /run /boot /usr /bin /sbin /lib /lib64);
    push @protected, qw(/root /var/lib/lxc /var/lib/pve-cluster /var/lib/pve-manager) if $host;
    for my $root (@protected) {
        die if $path eq $root || index($path, "$root/") == 0
            || ($host && index($root, "$path/") == 0);
    }
}

sub check_path_identity {
    my ($path, $expected, $device) = @_;
    die unless ref($expected) eq 'HASH' && join(',', sort keys %$expected) eq 'dev,gid,ino,mode,rdev,uid';
    die if grep { !defined($expected->{$_}) || ref($expected->{$_}) || $expected->{$_} !~ /\A[0-9]{1,20}\z/ } keys %$expected;
    my $walk = '';
    my @parts = grep { length($_) } split('/', $path);
    my @st;
    for my $index (0..$#parts) {
        $walk .= '/' . $parts[$index];
        @st = lstat($walk);
        die unless @st && !S_ISLNK($st[2]) && ($index == $#parts || S_ISDIR($st[2]));
    }
    die unless $device ? S_ISCHR($st[2]) : S_ISDIR($st[2]);
    my %actual = (dev => "$st[0]", ino => "$st[1]", rdev => "$st[6]",
                  uid => $st[4], gid => $st[5], mode => ($st[2] & 07777));
    die if grep { "$actual{$_}" ne "$expected->{$_}" } keys %actual;
}

sub hardware_config {
    my ($config, $resources, $vmid, $prepare) = @_;
    my $hardware = $resources->{hardware} // [];
    my $lxc = $config->{lxc} // [];
    die unless ref($hardware) eq 'ARRAY' && @$hardware <= 16 && ref($lxc) eq 'ARRAY';
    return [] if !@$hardware && !@$lxc;
    my @devices = map { my $d=$_; +{ map { $_ => $d->{$_} } qw(path uid gid mode) } } @{$resources->{devices}};
    require PVE::Tools;
    my $output = '';
    PVE::Tools::run_command(['/usr/bin/python3','-I','-B',
        File::Basename::dirname(__FILE__) . '/plain_lxc_resources.py',
        $prepare ? '--prepare-hardware' : '--check-hardware', '--json', "$vmid"],
        input => encode_json({hardware=>$hardware, lxc=>$lxc, devices=>\@devices}),
        timeout => 180, outfunc => sub { $output .= $_[0]; }, errfunc => sub {});
    my $entries = decode_json($output);
    die unless ref($entries) eq 'ARRAY' && @$entries <= 3;
    return $entries;
}

sub check_resources {
    my ($config, $resources, $vmid, $created) = @_;
    $resources //= {mounts=>[], devices=>[]};
    die unless ref($resources) eq 'HASH' && (join(',',sort keys %$resources) eq 'devices,mounts' || join(',',sort keys %$resources) eq 'devices,hardware,mounts');
    die unless ref($resources->{mounts}) eq 'ARRAY' && ref($resources->{devices}) eq 'ARRAY'
        && @{$resources->{mounts}} <= 16 && @{$resources->{devices}} <= 16;
    require PVE::LXC::Config;
    require PVE::Storage;
    my $properties = PVE::LXC::Config->json_config_properties({});
    my %wanted;
    my @paths;
    my $storage = PVE::Storage::config();
    for my $index (0..$#{$resources->{mounts}}) {
        my $key = "mp$index";
        my $item = $resources->{mounts}->[$index];
        die unless exists($properties->{$key}) && ref($item) eq 'HASH' && defined($config->{$key});
        my $kind = $item->{type} // '';
        die unless join(',',sort keys %$item) eq ($kind eq 'volume'
            ? 'backup,path,read_only,size_gib,storage,storage_type,type' : 'backup,identity,path,read_only,source,type');
        safe_mount_path($item->{path}, 0);
        for my $path (@paths) {
            die if $path eq $item->{path} || index($path, "$item->{path}/") == 0 || index($item->{path}, "$path/") == 0;
        }
        push @paths, $item->{path};
        my $actual = PVE::LXC::Config->parse_volume($key, $config->{$key});
        die unless $actual->{mp} eq $item->{path}
            && ($actual->{ro} // 0) == ($item->{read_only} ? 1 : 0)
            && ($actual->{backup} // 0) == ($item->{backup} ? 1 : 0);
        die if grep { $_ !~ /\A(?:volume|mp|ro|backup|size|type)\z/ } keys %$actual;
        if ($kind eq 'volume') {
            die unless ($item->{storage} // '') =~ /\A[A-Za-z][A-Za-z0-9_.-]{0,63}\z/
                && ($item->{size_gib} // '') =~ /\A[1-9][0-9]{0,4}\z/ && $item->{size_gib} <= 65536
                && ($storage->{ids}->{$item->{storage}}->{type} // '') eq $item->{storage_type}
                && $actual->{type} eq 'volume';
            if ($created) {
                my ($sid) = PVE::Storage::parse_volume_id($actual->{volume});
                my (undef, undef, $owner) = PVE::Storage::parse_volname($storage, $actual->{volume});
                die unless $sid eq $item->{storage} && defined($owner) && $owner == $vmid
                    && ($actual->{size} // 0) == $item->{size_gib} * 1073741824;
            } else {
                die unless $actual->{volume} eq "$item->{storage}:$item->{size_gib}";
            }
        } elsif ($kind eq 'bind') {
            safe_mount_path($item->{source}, 1);
            die unless !$item->{backup} && $actual->{type} eq 'bind' && $actual->{volume} eq $item->{source};
            check_path_identity($item->{source}, $item->{identity}, 0);
        } else { die; }
        $wanted{$key} = 1;
    }
    for my $index (0..$#{$resources->{devices}}) {
        my $key = "dev$index";
        my $item = $resources->{devices}->[$index];
        die unless exists($properties->{$key}) && ref($item) eq 'HASH'
            && join(',',sort keys %$item) eq 'gid,identity,mode,path,uid' && defined($config->{$key})
            && ($item->{path} // '') =~ m{\A/dev/(?:dri/(?:renderD[0-9]+|card[0-9]+)|kfd|apex_[0-9]+|accel/accel[0-9]+|nvidia(?:[0-9]+|ctl|-uvm(?:-tools)?)|bus/usb/[0-9]{3}/[0-9]{3}|tty(?:USB|ACM)[0-9]+)\z}
            && ($item->{mode} // '') =~ /\A0[0-7]{3}\z/;
        for my $id (qw(uid gid)) { die unless ($item->{$id} // '') =~ /\A[0-9]{1,10}\z/ && $item->{$id} <= 2147483647; }
        my $actual = PVE::LXC::Config->parse_device($config->{$key});
        die unless join(',',sort keys %$actual) eq 'gid,mode,path,uid';
        die if grep { "$actual->{$_}" ne "$item->{$_}" } qw(path uid gid mode);
        check_path_identity($item->{path}, $item->{identity}, 1);
        require PVE::Tools;
        # Reuse the shared read-only policy at the final native boundary too.
        # No host driver install, VFIO changes, chmod, guest command or shell.
        if (!exists($resources->{hardware})) {
            PVE::Tools::run_command(['/usr/bin/python3','-I','-B',
                File::Basename::dirname(__FILE__) . '/plain_lxc_resources.py', '--check-device', $item->{path}, "$vmid"],
                timeout => 180, outfunc => sub {}, errfunc => sub {});
        }
        $wanted{$key} = 1;
    }
    die if grep { /\A(?:mp|dev)[0-9]+\z/ && !$wanted{$_} } keys %$config;
    hardware_config($config,$resources,$vmid,0) if exists($resources->{hardware}) || @{$config->{lxc} // []};
}

sub storage_inventory {
    my ($node) = @_;
    require PVE::Storage;
    my $cfg = PVE::Storage::config();
    my $cache = {};
    my @result;
    # The storage and content GET endpoints call activate_storage, which
    # can mount NFS/CIFS or create directories. Use the reviewed built-in
    # status/list methods directly. Never call out to arbitrary plugins.
    my %supported = map { $_ => 1 } qw(dir btrfs nfs cifs cephfs lvm lvmthin zfspool rbd);
    for my $storage (sort keys %{$cfg->{ids}}) {
        my $scfg = PVE::Storage::storage_check_enabled($cfg, $storage, $node, 1) or next;
        my $type = $scfg->{type};
        next unless $supported{$type};
        my @content = grep { $scfg->{content}->{$_} } qw(rootdir vztmpl);
        next unless @content;
        my $plugin = PVE::Storage::Plugin->lookup($type);
        my (undef, $avail, undef, $active) = eval { $plugin->status($storage, $scfg, $cache) };
        if ($@ || !$active || !defined($avail)) {
            push @result, { storage => $storage, state => 'unavailable' };
            next;
        }
        my $volumes = $scfg->{content}->{vztmpl}
            ? $plugin->list_volumes($storage, $scfg, undef, ['vztmpl'])
            : [];
        push @result, { storage => $storage, state => 'available', type => $type, content => \@content,
            avail => int($avail), templates => $volumes };
    }
    return \@result;
}

sub bridge_vlans {
    # Older PVE releases may lack the native link helpers. Let the caller
    # retain its configured VLAN-aware check in that case.
    return undef unless eval { require PVE::IPRoute2; 1 }
        && !grep { !PVE::IPRoute2->can($_) } qw(ip_link_details ip_link_is_bridge
            bridge_is_vlan_aware get_physical_bridge_ports);
    my $links = PVE::IPRoute2::ip_link_details();
    my %bridges;
    for my $name (keys %$links) {
        my $link = $links->{$name};
        next unless PVE::IPRoute2::ip_link_is_bridge($link);
        # PVE also accepts a single tag on a traditional Linux bridge
        # when it has an eligible physical, bonded or VLAN uplink.
        $bridges{$name} = PVE::IPRoute2::bridge_is_vlan_aware($link)
            || scalar(PVE::IPRoute2::get_physical_bridge_ports($name, $links)) ? 1 : 0;
    }
    return \%bridges;
}

sub inventory {
    my ($node, $params) = @_;
    my $vmid = $params->{vmid};
    die if keys %$params && (join(',', sort keys %$params) ne 'vmid'
        || !defined($vmid) || ref($vmid) || $vmid !~ /\A[1-9][0-9]{2,8}\z/);
    my $prefix = "/nodes/$node";
    # Reuse one PVE initialization for the fixed, read-only calls.
    my $status = handle('GET', "$prefix/status", {});
    my $catalog = eval { handle('GET', "$prefix/aplinfo", {}) };
    my $storages = storage_inventory($node);
    my $network = handle('GET', "$prefix/network", {});
    my $has_linux_bridge = grep { ($_->{type} // '') eq 'bridge' && $_->{active} } @$network;
    my $data = {
        status => $status, catalog => $catalog, storages => $storages, network => $network,
        bridge_vlans => $has_linux_bridge ? bridge_vlans() : {},
    };
    require PVE::LXC::Config;
    my $properties = PVE::LXC::Config->json_config_properties({});
    $data->{capabilities} = {
        mount_points => scalar(grep { /\Amp[0-9]+\z/ } keys %$properties),
        devices => scalar(grep { /\Adev[0-9]+\z/ } keys %$properties),
    };
    if (defined($vmid)) {
        $data->{guests} = handle('GET', '/cluster/resources', { type => 'vm' });
        # Keep the guest list so the caller can distinguish a collision
        # from a failed next-ID check.
        $data->{nextid} = eval { handle('GET', '/cluster/nextid', { vmid => $vmid }) };
    }
    return $data;
}

sub dispatch {
    my ($request) = @_;
    die unless $> == 0 && ref($request) eq 'HASH'
        && join(',', sort keys %$request) eq 'action,node,params';
    my ($action, $node, $params) = @$request{qw(action node params)};
    die unless defined($node) && $node =~ /\A[A-Za-z0-9-]{1,63}\z/ && ref($params) eq 'HASH';
    require PVE::INotify;
    my $expected = $node;
    if ($action eq 'inspect') {
        # Validate before the first probe. localhost is only a discovery token,
        # never a permitted target for a mutation.
        die if keys %$params && (join(',', sort keys %$params) ne 'vmid'
            || !defined($params->{vmid}) || ref($params->{vmid})
            || $params->{vmid} !~ /\A[1-9][0-9]{2,8}\z/);
        $node = PVE::INotify::nodename();
    } else {
        die unless $node eq PVE::INotify::nodename();
    }
    require PVE::RPCEnvironment;
    require PVE::API2;
    PVE::INotify::inotify_init();
    # The CLI RPC mode waits in the handler and can lose the UPID on timeout.
    # Use the same asynchronous worker mode as the local privileged API.
    my $rpcenv = PVE::RPCEnvironment->init('priv', atfork => sub {
        close($response) if defined(fileno($response));
    });
    $rpcenv->init_request();
    $rpcenv->set_user('root@pam');

    if ($action eq 'inspect') {
        my $nodes = handle('GET', '/cluster/status', {});
        my $result = { nodes => $nodes };
        # Keep malformed/offline discovery for Python's existing error codes,
        # but do not probe inventory for it or for another target node.
        return $result unless ref($nodes) eq 'ARRAY';
        my @local;
        for my $row (@$nodes) {
            return $result unless ref($row) eq 'HASH';
            next unless ($row->{type} // '') eq 'node';
            return $result unless ($row->{local} // '0') =~ /\A[01]\z/;
            push @local, $row if $row->{local};
        }
        return $result unless @local == 1 && ($local[0]->{online} // '') eq '1'
            && ($local[0]->{name} // '') eq $node
            && ($expected eq 'localhost' || $expected eq $node);
        $result->{inventory} = inventory($node, $params);
        $result->{nextid} = eval { handle('GET', '/cluster/nextid', {}) }
            unless exists($params->{vmid});
        return $result;
    }

    my $prefix = "/nodes/$node";
    my $vmid = $params->{vmid} // '';
    my $marker = qr/\AProxMenux request [a-f0-9]{32}\z/;
    my $storage_id = qr/[A-Za-z][A-Za-z0-9_.-]{0,63}/;
    if ($action eq 'inventory') {
        return inventory($node, $params);
    }
    if ($action eq 'recovery_check') {
        my $is_create = exists($params->{vmid});
        die unless join(',', sort keys %$params) eq ($is_create ? 'description,vmid' : 'description,volume_id')
            && ($params->{description} // '') =~ $marker;
        die if $is_create && $vmid !~ /\A[1-9][0-9]{2,8}\z/;
        die if !$is_create && ($params->{volume_id} // '') !~ m{\A${storage_id}:vztmpl/[A-Za-z0-9][A-Za-z0-9_.+-]*\z};
        # A killed controller may have left a dispatcher before fork_worker.
        # Reject while any other instance is alive, even for another request.
        for my $file (glob('/proc/[0-9]*/cmdline')) {
            next if $file eq "/proc/$$/cmdline";
            open(my $fh, '<', $file) or do { die if -e $file; next; };
            local $/; my $args = <$fh> // ''; close($fh);
            die if grep { m{(?:\A|/)plain_lxc_pve\.pl\z} } split(/\0/, $args);
        }
        my $idle = sub {
            # active_workers includes a few recently finished tasks as well.
            # Any running/unknown task conservatively prevents release. Never
            # use a paginated task GET that might omit the relevant worker.
            my $tasks = $rpcenv->active_workers();
            die unless ref($tasks) eq 'ARRAY';
            for my $task (@$tasks) {
                die unless ref($task) eq 'HASH' && defined($task->{upid})
                    && defined($task->{endtime}) && $task->{endtime} =~ /\A[0-9]+\z/
                    && !defined($task->{pid});
            }
        };
        if ($is_create) {
            require PVE::LXC::Config;
            return PVE::LXC::Config->lock_config($vmid, sub {
                $idle->();
                my $guests = handle('GET', '/cluster/resources', { type => 'vm' });
                die unless ref($guests) eq 'ARRAY';
                my $present = 0;
                for my $guest (@$guests) {
                    die unless ref($guest) eq 'HASH' && defined($guest->{vmid});
                    next unless $guest->{vmid} eq $vmid;
                    die unless ($guest->{type} // '') eq 'lxc' && ($guest->{node} // '') eq $node;
                    my $config = PVE::LXC::Config->load_config($vmid);
                    my $description = $config->{description} // '';
                    die unless !$config->{lock} && ($description eq $params->{description}
                        || $description eq $params->{description} . "\n");
                    $present = 1;
                }
                return { safe => 1, present => $present };
            });
        }
        $idle->();
        require PVE::Storage;
        my $path = PVE::Storage::path(PVE::Storage::config(), $params->{volume_id});
        die if -l $path || (-e $path && !-f $path);
        return { safe => 1, present => -f $path ? 1 : 0 };
    }
    if ($action eq 'create') {
        my %allowed = map { $_ => 1 } qw(vmid hostname ostemplate storage rootfs cores memory swap
            unprivileged features onboot start description password ssh-public-keys net0 nameserver searchdomain arch resource_identity);
        die if grep { !$allowed{$_} && !/\A(?:mp|dev)(?:[0-9]|1[0-5])\z/ } keys %$params;
        my $storage = $params->{storage} // '';
        die unless $vmid =~ /\A[1-9][0-9]{2,8}\z/
            && $storage =~ /\A$storage_id\z/
            && ($params->{rootfs} // '') =~ /\A\Q$storage\E:[1-9][0-9]*\z/
            && ($params->{ostemplate} // '') =~ m{\A${storage_id}:vztmpl/[A-Za-z0-9][A-Za-z0-9_.+-]*\z}
            && ($params->{description} // '') =~ $marker
            && ($params->{unprivileged} // '') eq '1'
            && ($params->{features} // '') =~ /\Anesting=[01]\z/
            && (!exists($params->{arch}) || ($params->{arch} // '') =~ /\A(?:amd64|arm64)\z/)
            && ($params->{start} // '') eq '0';
        my $resources = delete $params->{resource_identity};
        check_resources($params, $resources, $vmid, 0);
        return handle('POST', "$prefix/lxc", $params);
    }
    if ($action eq 'start' || $action eq 'prepare') {
        die unless join(',', sort keys %$params) eq 'description,expected,vmid'
            && $vmid =~ /\A[1-9][0-9]{2,8}\z/ && $params->{description} =~ $marker
            && ref($params->{expected}) eq 'HASH';
        my $expected = $params->{expected};
        # Missing flag belongs to an already admitted pre-option request.
        # New requests always carry an explicit boolean in their reviewed plan.
        my $prepare_system = exists($expected->{prepare_system}) ? $expected->{prepare_system} : 1;
        die unless "$prepare_system" =~ /\A[01]\z/;
        my $prepare_hardware = ref($expected->{resources}) eq 'HASH'
            && ref($expected->{resources}->{hardware}) eq 'ARRAY'
            && grep { ref($_) eq 'HASH' && ref($_->{runtime}) eq 'HASH' } @{$expected->{resources}->{hardware}};
        die if $action eq 'prepare' && !$prepare_system && !$prepare_hardware;
        my %identity = %$expected;
        delete @identity{qw(prepare_system resources arch)};
        die if exists($expected->{arch}) && ($expected->{arch} // '') !~ /\A(?:amd64|arm64)\z/;
        die unless join(',', sort keys %identity) eq 'cores,features,hostname,memory,net0,onboot,storage,storage_type,swap'
            && ($expected->{storage} // '') =~ /\A$storage_id\z/
            && ($expected->{storage_type} // '') =~ /\A(?:dir|btrfs|nfs|cifs|cephfs|lvm|lvmthin|zfspool|rbd)\z/
            && ($expected->{features} // '') =~ /\Anesting=[01]\z/
            && ($expected->{hostname} // '') =~ /\A[a-z0-9][a-z0-9.-]{0,252}\z/
            && ($expected->{onboot} // '') =~ /\A[01]\z/
            && !grep { !defined($expected->{$_}) || ref($expected->{$_}) || $expected->{$_} !~ /\A[0-9]{1,9}\z/ } qw(cores memory swap);
        die if defined($expected->{net0}) && (ref($expected->{net0}) || length($expected->{net0}) > 1024);
        require PVE::LXC;
        require PVE::LXC::Config;
        require PVE::HA::Config;
        require PVE::Storage;
        require PVE::Tools;
        require PVE::ProcFSTools;
        my $worker = sub {
            my $prepared = 0;
            eval { PVE::LXC::Config->lock_config($vmid, sub {
                my $config = PVE::LXC::Config->load_config($vmid);
                my $description = $config->{description} // '';
                die "ProxMenux preparation failed: identity_or_state\n"
                    unless ($description eq $params->{description} || $description eq $params->{description} . "\n")
                    && !$config->{lock} && !$config->{template} && ($config->{unprivileged} // '') eq '1'
                    && !PVE::LXC::check_running($vmid) && !PVE::HA::Config::vm_is_ha_managed($vmid)
                    && !keys %{$config->{pending} // {}}
                    && (!exists($config->{lxc}) || (ref($config->{lxc}) eq 'ARRAY' && (!@{$config->{lxc}} || $prepare_hardware)))
                    && !grep { /\A(?:unused[0-9]+|hookscript)\z/ } keys %$config;
                check_resources($config, $expected->{resources}, $vmid, 1);
                die "ProxMenux preparation failed: architecture_changed\n"
                    if exists($expected->{arch}) && ($config->{arch} // '') ne $expected->{arch};
                for my $key (qw(hostname features cores memory swap onboot)) {
                    die "ProxMenux preparation failed: configuration_changed\n"
                        unless defined($config->{$key}) && "$config->{$key}" eq "$expected->{$key}";
                }
                my @networks = grep { /\Anet[0-9]+\z/ } keys %$config;
                die "ProxMenux preparation failed: network_changed\n"
                    if defined($expected->{net0}) ? (@networks != 1 || $networks[0] ne 'net0') : @networks;
                if (defined($expected->{net0})) {
                    my %wanted = map { split(/=/, $_, 2) } split(/,/, $expected->{net0});
                    my $actual = PVE::LXC::Config->parse_lxc_network($config->{net0});
                    delete $actual->{hwaddr};
                    die "ProxMenux preparation failed: network_changed\n"
                        unless join(',', sort keys %$actual) eq join(',', sort keys %wanted);
                    for my $key (keys %wanted) {
                        die "ProxMenux preparation failed: network_changed\n" unless "$actual->{$key}" eq "$wanted{$key}";
                    }
                }
                my $storage = PVE::Storage::config();
                die "ProxMenux preparation failed: storage_changed\n"
                    unless ($storage->{ids}->{$expected->{storage}}->{type} // '') eq $expected->{storage_type};
                my $rootfs = PVE::LXC::Config->parse_volume('rootfs', $config->{rootfs});
                my ($sid) = PVE::Storage::parse_volume_id($rootfs->{volume});
                my (undef, undef, $owner) = PVE::Storage::parse_volname($storage, $rootfs->{volume});
                die "ProxMenux preparation failed: unsafe_rootfs\n"
                    unless $rootfs->{type} eq 'volume' && !$rootfs->{ro} && !$rootfs->{quota}
                    && !$rootfs->{mountoptions} && !$rootfs->{idmap}
                    && $sid eq $expected->{storage} && defined($owner) && $owner == $vmid;
                if ($prepare_hardware) {
                    my $entries = hardware_config($config,$expected->{resources},$vmid,1);
                    if (encode_json($config->{lxc} // []) ne encode_json($entries)) {
                        $config->{lxc} = $entries;
                        PVE::LXC::Config->write_config($vmid,$config);
                    }
                    hardware_config($config,$expected->{resources},$vmid,0);
                    print "ProxMenux: hardware preparation completed\n";
                }
                if (!$prepare_system) {
                    # Native start with the same identity lock, without mounting
                    # or modifying the guest filesystem at all.
                    $prepared = 1;
                    PVE::LXC::vm_start($vmid, $config, 0, 0) if $action eq 'start';
                    return;
                }
                my $root = "/var/lib/lxc/$vmid/rootfs";
                my $stage = "/var/lib/lxc/.pve-staged-mounts/$vmid.all";
                die "ProxMenux preparation failed: already_mounted\n"
                    if PVE::ProcFSTools::is_mounted($root) || PVE::ProcFSTools::is_mounted($stage);
                my (undef, $uid, $gid) = PVE::LXC::parse_id_maps($config);
                die "ProxMenux preparation failed: unsafe_id_map\n" unless $uid > 0 && $gid > 0;
                my $error;
                # Only the root volume is mounted for opt-in preparation.
                # Never traverse or activate a host bind mount or data volume.
                my %prepare_config = map { $_ => $config->{$_} } grep { !/\A(?:mp|dev)[0-9]+\z/ } keys %$config;
                eval {
                    my $mounted = PVE::LXC::mount_all($vmid, $storage, \%prepare_config);
                    die "unexpected mount path\n" unless defined($mounted) && $mounted eq $root;
                    print "ProxMenux: preparing first boot\n";
                    PVE::Tools::run_command(['/usr/bin/python3', '-I', '-B', File::Basename::dirname(__FILE__) . '/plain_lxc_prepare.py',
                        $root, "$uid", "$gid", defined($expected->{net0}) ? '0' : '1'], timeout => 30);
                };
                $error = $@;
                # A partially failed mount also needs native cleanup. Never
                # submit a start after an uncertain or failed unmount.
                eval {
                    die "unmount not confirmed\n" unless PVE::LXC::umount_all($vmid, $storage, \%prepare_config, 0);
                };
                $error .= $@ if $@;
                $error ||= "rootfs still mounted\n" if PVE::ProcFSTools::is_mounted($root);
                $error ||= "staging mount still present\n" if PVE::ProcFSTools::is_mounted($stage);
                die "ProxMenux preparation failed: $error" if $error;
                die "ProxMenux preparation failed: storage_changed\n"
                    unless (PVE::Storage::config()->{ids}->{$expected->{storage}}->{type} // '') eq $expected->{storage_type};
                print "ProxMenux: first-boot preparation completed\n";
                $prepared = 1;
                PVE::LXC::vm_start($vmid, $config, 0, 0) if $action eq 'start';
            }); };
            if (my $error = $@) {
                if (!$prepare_system && !$prepare_hardware) {
                    $error =~ s/ProxMenux preparation failed:/ProxMenux start validation failed:/g;
                    die $error;
                }
                die $prepared ? $error : "ProxMenux preparation failed: $error";
            }
        };
        return $rpcenv->fork_worker($action eq 'start' ? 'vzstart' : 'vzprepare', $vmid, 'root@pam', $worker);
    }
    if ($action eq 'download_template') {
        die unless join(',', sort keys %$params) eq 'architecture,sha512,storage,template';
        my ($arch, $checksum, $storage, $template) = @$params{qw(architecture sha512 storage template)};
        die unless $storage =~ /\A$storage_id\z/
            && $template =~ /\A[A-Za-z0-9][A-Za-z0-9_.+-]{0,179}\z/ && $template !~ /\.\./
            && $checksum =~ /\A[a-f0-9]{128}\z/;
        require PVE::APLInfo;
        require PVE::Storage;
        my $entry = PVE::APLInfo::load_data()->{all}->{$template} // {};
        my $system = ($entry->{section} // '') eq 'system'
            && ($entry->{source} // '') =~ m{\Ahttps?://download\.proxmox\.com/images\z}
            && ($entry->{location} // '') =~ m{\Ahttps?://download\.proxmox\.com/images/system/\Q$template\E\z};
        my $turnkey = ($entry->{source} // '') eq 'https://releases.turnkeylinux.org/pve'
            && (($entry->{location} // '') =~ m{\Ahttps://releases\.turnkeylinux\.org/pve/(?:[A-Za-z0-9_.+-]+/)*\Q$template\E\z}
                || ($entry->{location} // '') =~ m{\Ahttps?://mirror\.turnkeylinux\.org/turnkeylinux/images/proxmox/\Q$template\E\z})
            && ($entry->{location} // '') !~ m{(?:\A|/)\.\.(?:/|\z)};
        die unless ($system || $turnkey) && ($entry->{type} // '') eq 'lxc'
            && ($entry->{architecture} // '') eq $arch && lc($entry->{sha512sum} // '') eq $checksum;
        my $path = PVE::Storage::path(PVE::Storage::config(), "$storage:vztmpl/$template");
        die if -e $path || -l $path;
        return handle('POST', "$prefix/aplinfo", { storage => $storage, template => $template });
    }
    die;
}

my $data = eval {
    my $raw = '';
    while (length($raw) <= 131072) {
        my $n = read(STDIN, my $chunk, 8192);
        die unless defined($n);
        last unless $n;
        $raw .= $chunk;
    }
    die if length($raw) > 131072;
    dispatch(decode_json($raw));
};
exit 1 if $@ || !defined($data);
print {$response} encode_json($data);
