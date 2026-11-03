<?php
// Prepare a fresh LinuxServer Nextcloud without replacing persistent user settings.
$dir = '/config/www/nextcloud/config';
if (!is_dir($dir) && !mkdir($dir, 0770, true)) { throw new RuntimeException('Cannot create the Nextcloud config directory'); }
if (!is_file($dir . '/config.php') && !is_file($dir . '/autoconfig.php')) {
    foreach (['MYSQL_HOST', 'MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD'] as $name) {
        if (getenv($name) === false || getenv($name) === '') { throw new RuntimeException('Missing Nextcloud database setting: ' . $name); }
    }
    // Keep the defaults that LinuxServer copies only into an empty config directory.
    $defaults = '/app/www/src/config';
    if (is_dir($defaults)) {
        foreach (new DirectoryIterator($defaults) as $file) {
            if ($file->isDot() || !$file->isFile()) { continue; }
            $target = $dir . '/' . $file->getFilename();
            if (!file_exists($target) && !copy($file->getPathname(), $target)) { throw new RuntimeException('Cannot seed the Nextcloud configuration'); }
        }
    }
    $settings = ['dbtype' => 'mysql', 'dbhost' => getenv('MYSQL_HOST'), 'dbname' => getenv('MYSQL_DATABASE'), 'dbuser' => getenv('MYSQL_USER'), 'dbpass' => getenv('MYSQL_PASSWORD'), 'directory' => '/data'];
    $path = $dir . '/autoconfig.php';
    if (file_put_contents($path, "<?php\n\$AUTOCONFIG = " . var_export($settings, true) . ";\n", LOCK_EX) === false) { throw new RuntimeException('Cannot write the Nextcloud database configuration'); }
    chmod($path, 0600);
}
$path = $dir . '/proxmenux-redis.config.php';
if (!is_file($path)) {
    $settings = ['filelocking.enabled' => true, 'memcache.local' => '\OC\Memcache\APCu', 'memcache.locking' => '\OC\Memcache\Redis', 'redis' => ['host' => 'redis', 'port' => 6379, 'timeout' => 0.0]];
    if (file_put_contents($path, "<?php\n\$CONFIG = " . var_export($settings, true) . ";\n", LOCK_EX) === false) { throw new RuntimeException('Cannot write the Nextcloud Redis configuration'); }
    chmod($path, 0600);
}
