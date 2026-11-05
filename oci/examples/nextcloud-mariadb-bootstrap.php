<?php
// Prepare a fresh LinuxServer Nextcloud without replacing persistent user settings.
$dir = '/config/www/nextcloud/config';
umask(0077);
if (!is_dir($dir) && !mkdir($dir, 0770, true)) { throw new RuntimeException('Cannot create the Nextcloud config directory'); }
// The directory belongs to the application user. Create each file without
// following a link placed there, and give it to that user without following one.
function create_private($path, $content, $owner) {
    $handle = @fopen($path, 'x');
    if ($handle === false || fwrite($handle, $content) !== strlen($content) || !fclose($handle)) { throw new RuntimeException('Cannot write ' . basename($path)); }
    if ($owner && (!lchown($path, fileowner($owner)) || !lchgrp($path, filegroup($owner)))) { throw new RuntimeException('Cannot set Nextcloud configuration ownership'); }
}
if (!is_file($dir . '/config.php') && !is_file($dir . '/autoconfig.php')) {
    foreach (['MYSQL_HOST', 'MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD', 'NEXTCLOUD_ADMIN_PASSWORD'] as $name) {
        if (getenv($name) === false || getenv($name) === '') { throw new RuntimeException('Missing Nextcloud setting: ' . $name); }
    }
    // Keep the defaults that LinuxServer copies only into an empty config directory.
    $defaults = '/app/www/src/config';
    if (is_dir($defaults)) {
        foreach (new DirectoryIterator($defaults) as $file) {
            if ($file->isDot() || !$file->isFile()) { continue; }
            $target = $dir . '/' . $file->getFilename();
            if (!file_exists($target) && !is_link($target)) { create_private($target, file_get_contents($file->getPathname()), null); }
        }
    }
    // With the administrator included, Nextcloud installs itself on the first
    // request, so nobody else on the network can claim the setup page.
    $settings = ['dbtype' => 'mysql', 'dbhost' => getenv('MYSQL_HOST'), 'dbname' => getenv('MYSQL_DATABASE'), 'dbuser' => getenv('MYSQL_USER'), 'dbpass' => getenv('MYSQL_PASSWORD'), 'directory' => '/data', 'adminlogin' => 'admin', 'adminpass' => getenv('NEXTCLOUD_ADMIN_PASSWORD')];
    // Existing installations skip LinuxServer's first-run ownership setup.
    create_private($dir . '/autoconfig.php', "<?php\n\$AUTOCONFIG = " . var_export($settings, true) . ";\n", $dir);
}
$path = $dir . '/proxmenux-redis.config.php';
// Installed instances keep their existing cache configuration unchanged.
if (!is_file($path) && !is_link($path) && !is_file($dir . '/config.php')) {
    $settings = ['filelocking.enabled' => true, 'memcache.local' => '\OC\Memcache\APCu', 'memcache.locking' => '\OC\Memcache\Redis', 'redis' => ['host' => 'redis', 'port' => 6379, 'timeout' => 0.0]];
    create_private($path, "<?php\n\$CONFIG = " . var_export($settings, true) . ";\n", $dir);
}
