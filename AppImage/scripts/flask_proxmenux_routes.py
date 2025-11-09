from flask import Blueprint, jsonify
import json
import os

proxmenux_bp = Blueprint('proxmenux', __name__)

# Tool descriptions mapping
TOOL_DESCRIPTIONS = {
    'lvm_repair': 'LVM PV Headers Repair',
    'repo_cleanup': 'Repository Cleanup',
    'subscription_banner': 'Subscription Banner Removal',
    'time_sync': 'Time Synchronization',
    'apt_languages': 'APT Language Skip',
    'journald': 'Journald Optimization',
    'logrotate': 'Logrotate Optimization',
    'system_limits': 'System Limits Increase',
    'entropy': 'Entropy Generation (haveged)',
    'memory_settings': 'Memory Settings Optimization',
    'kernel_panic': 'Kernel Panic Configuration',
    'apt_ipv4': 'APT IPv4 Force',
    'kexec': 'kexec for quick reboots',
    'network_optimization': 'Network Optimizations',
    'bashrc_custom': 'Bashrc Customization',
    'figurine': 'Figurine',
    'fastfetch': 'Fastfetch',
    'log2ram': 'Log2ram (SSD Protection)',
    'amd_fixes': 'AMD CPU (Ryzen/EPYC) fixes',
    'persistent_network': 'Setting persistent network interfaces'
}

@proxmenux_bp.route('/api/proxmenux/installed-tools', methods=['GET'])
def get_installed_tools():
    """Get list of installed ProxMenux tools/optimizations"""
    installed_tools_path = '/usr/local/share/proxmenux/installed_tools.json'
    
    try:
        if not os.path.exists(installed_tools_path):
            return jsonify({
                'success': True,
                'installed_tools': [],
                'message': 'No ProxMenux optimizations installed yet'
            })
        
        with open(installed_tools_path, 'r') as f:
            data = json.load(f)
        
        # Convert to list format with descriptions
        tools = []
        for tool_key, enabled in data.items():
            if enabled:  # Only include enabled tools
                tools.append({
                    'key': tool_key,
                    'name': TOOL_DESCRIPTIONS.get(tool_key, tool_key.replace('_', ' ').title()),
                    'enabled': enabled
                })
        
        # Sort alphabetically by name
        tools.sort(key=lambda x: x['name'])
        
        return jsonify({
            'success': True,
            'installed_tools': tools,
            'total_count': len(tools)
        })
    
    except json.JSONDecodeError:
        return jsonify({
            'success': False,
            'error': 'Invalid JSON format in installed_tools.json'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
