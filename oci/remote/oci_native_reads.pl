#!/usr/bin/perl
# Operation-scoped read-only PVE API worker. No socket, cache or write methods.
use strict;
use warnings;
use JSON::PP;
use IO::Handle;
BEGIN { die "root required\n" if $> != 0; }
use PVE::Cluster;
use PVE::RPCEnvironment;
use PVE::API2::Cluster;
use PVE::API2::HA::Resources;
use PVE::API2::LXC::Config;
use PVE::LXC;
use PVE::Tools;

STDOUT->autoflush(1);
PVE::RPCEnvironment->setup_default_cli_env();
my $json = JSON::PP->new->utf8->canonical;
while (my $line = <STDIN>) {
    last if length($line) > 4096;
    my $request = eval { $json->decode($line) };
    last if $@ || ref($request) ne 'HASH';
    my $seq = $request->{id};
    last if !defined($seq) || ref($seq) || $seq !~ /^[1-9][0-9]*$/;
    my $reply = { id => 0 + $seq, ok => JSON::PP::false };
    eval {
        my $op = $request->{op} // '';
        die "invalid request\n" if grep { $_ ne 'id' && $_ ne 'op' && $_ ne 'vmid' } keys %$request;
        # Refresh pmxcfs versions on EVERY request, including reads after pct
        # writes, external changes, guest creation/removal and node migration.
        PVE::Cluster::cfs_update(1);
        my $result;
        if ($op eq 'config' || $op eq 'status') {
            my $vmid = $request->{vmid};
            die "invalid vmid\n" if !defined($vmid) || ref($vmid)
                || $vmid !~ /^[1-9][0-9]{2,8}$/;
            if ($op eq 'config') {
                # Same native API and text representation as `pct config`:
                # pending values, escaped description and repeated lxc keys.
                my $config = PVE::API2::LXC::Config->vm_config({
                    node => PVE::INotify::nodename(), vmid => 0 + $vmid });
                $result = '';
                for my $key (sort keys %$config) {
                    next if $key eq 'digest' || $key eq 'lxc';
                    my $value = $config->{$key};
                    $value = PVE::Tools::encode_text($value) if $key eq 'description';
                    $result .= "$key: $value\n";
                }
                if (defined(my $options = $config->{lxc})) {
                    for my $option (@$options) {
                        $result .= "$option->[0]: $option->[1]\n";
                    }
                }
            } else {
                # Match `pct status` including refusing a missing config.
                PVE::LXC::Config->load_config($vmid);
                my $states = PVE::LXC::vmstatus($vmid);
                my $status = $states->{$vmid}->{status} || 'unknown';
                $result = "status: $status\n";
            }
        } elsif ($op eq 'resources' && !exists($request->{vmid})) {
            $result = PVE::API2::Cluster->resources({ type => 'vm' });
        } elsif ($op eq 'ha' && !exists($request->{vmid})) {
            $result = PVE::API2::HA::Resources->index({});
        } else {
            die "unsupported operation\n";
        }
        $reply->{result} = $result;
        $reply->{ok} = JSON::PP::true;
    };
    # Never return/log exception text: PVE configurations may contain secrets.
    # A failure makes the client use the ordinary CLI afresh, with its normal
    # errors and validation. No previous response is ever used as a fallback.
    print $json->encode($reply), "\n";
}
