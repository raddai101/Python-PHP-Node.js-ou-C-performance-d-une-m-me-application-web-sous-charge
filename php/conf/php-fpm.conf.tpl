; Modèle de configuration PHP-FPM (les __VARIABLES__ sont remplacées par scripts/server.sh)
[global]
pid = __RUN__/php/php-fpm.pid
error_log = __RUN__/php/php-fpm.log
daemonize = yes

[www]
__POOL_USER__
listen = __RUN__/php/php-fpm.sock
listen.mode = 0666

; Pool dynamique, conforme au dossier de référence (PARTIE 3)
pm = dynamic
pm.max_children = 20
pm.start_servers = 5
pm.min_spare_servers = 5
pm.max_spare_servers = 10

; Réglages de production
php_admin_value[opcache.enable] = 1
php_admin_value[opcache.validate_timestamps] = 0
php_admin_value[max_execution_time] = 120
php_admin_flag[display_errors] = off
