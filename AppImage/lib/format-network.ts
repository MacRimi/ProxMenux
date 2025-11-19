/**
 * Utility functions for formatting network traffic data
 * Supports conversion between Bytes and Bits based on user preferences
 */

export type NetworkUnit = 'Bytes' | 'Bits';

/**
 * Format network traffic value with appropriate unit
 * @param bytes - Value in bytes
 * @param unit - Target unit ('Bytes' or 'Bits')
 * @param decimals - Number of decimal places (default: 2)
 * @returns Formatted string with value and unit
 */
export function formatNetworkTraffic(
  bytes: number,
  unit: NetworkUnit = 'Bytes',
  decimals: number = 2
): string {
  if (bytes === 0) return unit === 'Bits' ? '0 b' : '0 B';

  const k = unit === 'Bits' ? 1000 : 1024;
  const dm = decimals < 0 ? 0 : Math.min(decimals, 2);
  
  // For Bits: convert bytes to bits first (multiply by 8)
  const value = unit === 'Bits' ? bytes * 8 : bytes;
  
  const sizes = unit === 'Bits' 
    ? ['b', 'Kb', 'Mb', 'Gb', 'Tb', 'Pb']
    : ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

  const i = Math.floor(Math.log(value) / Math.log(k));
  const finalDecimals = i >= 3 ? 2 : 2;
  const formattedValue = parseFloat((value / Math.pow(k, i)).toFixed(finalDecimals));

  return `${formattedValue} ${sizes[i]}`;
}

/**
 * Get the current network unit preference from localStorage
 * @returns 'Bytes' or 'Bits'
 */
export function getNetworkUnit(): NetworkUnit {
  if (typeof window === 'undefined') return 'Bytes';
  
  const stored = localStorage.getItem('proxmenux-network-unit');
  return stored === 'Bits' ? 'Bits' : 'Bytes';
}

/**
 * Get the label for network traffic based on current unit
 * @param direction - 'received' or 'sent'
 * @returns Label string
 */
export function getNetworkLabel(direction: 'received' | 'sent'): string {
  const unit = getNetworkUnit();
  const prefix = direction === 'received' ? 'Received' : 'Sent';
  return unit === 'Bits' ? `${prefix}` : `${prefix}`;
}

/**
 * Get the unit suffix for displaying in charts
 * @returns Unit suffix string (e.g., 'GB' or 'Gb')
 */
export function getNetworkUnitSuffix(): string {
  const unit = getNetworkUnit();
  return unit === 'Bits' ? 'b' : 'B';
}
