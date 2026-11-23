use strict;
use warnings;
use JSON qw(encode_json);
use PVE::API2;
use PVE::INotify;
use PVE::RPCEnvironment;

my ($node, $guest_type, $vmid, $mode) = @ARGV;
exit 2 unless (@ARGV == 3 || (@ARGV == 4 && $mode =~ /\Asettings(?:-network)?\z/))
    && $node =~ /\A[A-Za-z0-9][A-Za-z0-9.-]*\z/
    && $node eq PVE::INotify::nodename()
    && $guest_type =~ /\A(?:qemu|lxc)\z/
    && $vmid =~ /\A[0-9]+\z/;

PVE::RPCEnvironment->setup_default_cli_env();

sub read_api {
    my ($path, $type, $params) = @_;
    my $data = eval {
        # pvesh uses the same handler locally. The caller supplies only a
        # validated local guest and this program constructs every GET path.
        $params //= {};
        my ($handler, $info) = PVE::API2->find_handler('GET', $path, $params);
        die "unsupported endpoint\n" unless $handler && $info && !$info->{expose_credentials};
        $handler->handle($info, $params);
    };
    return ref($data) eq $type ? $data : undef;
}

my $node_path = "/nodes/$node";
my $guest_path = "$node_path/$guest_type/$vmid";
my $guest = read_api("$guest_path/firewall/options", 'HASH') // exit 2;
if (defined($mode)) {
    my $config = read_api("$guest_path/config", 'HASH') // exit 2;
    my $pending = read_api("$guest_path/pending", 'ARRAY') // exit 2;
    my $bridges = $mode eq 'settings-network'
        ? read_api("$node_path/network", 'ARRAY', { type => 'any_bridge' }) : [];
    print STDOUT encode_json({ options => $guest, config => { digest => $config->{digest} },
                               pending => $pending, bridges => $bridges });
    exit 0;
}
my $host = read_api("$node_path/firewall/options", 'HASH');
my $cluster = read_api('/cluster/firewall/options', 'HASH');
my $config = read_api("$guest_path/pending", 'ARRAY');

my $service;
if (defined($host)) {
    my $enabled = $host->{nftables} // '0';
    my %units = ('0' => 'pve-firewall', '1' => 'proxmox-firewall');
    if (my $unit = $units{$enabled}) {
        $service = read_api("$node_path/services/$unit/state", 'HASH');
    }
}

print STDOUT encode_json({
    guest => $guest,
    host => $host,
    cluster => $cluster,
    config => $config,
    service => $service,
});
