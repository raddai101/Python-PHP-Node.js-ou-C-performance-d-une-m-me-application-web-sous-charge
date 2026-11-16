# Modèle de configuration Nginx (les __VARIABLES__ sont remplacées par scripts/server.sh)
__USER_DIRECTIVE__
worker_processes auto;
pid __RUN__/php/nginx.pid;
error_log __RUN__/php/nginx-error.log warn;
daemon on;

events {
    worker_connections 1024;
}

http {
    access_log off;
    sendfile on;
    keepalive_timeout 65;

    # Répertoires temporaires dans run/ : Nginx peut tourner sans droits root.
    client_body_temp_path __RUN__/php/tmp/client;
    proxy_temp_path       __RUN__/php/tmp/proxy;
    fastcgi_temp_path     __RUN__/php/tmp/fastcgi;
    uwsgi_temp_path       __RUN__/php/tmp/uwsgi;
    scgi_temp_path        __RUN__/php/tmp/scgi;

    server {
        listen 127.0.0.1:8081;
        root __ROOT__/php/public;

        # Les réponses (~70 Ko pour /tasks) tiennent en mémoire : pas de fichier temporaire.
        fastcgi_buffer_size 32k;
        fastcgi_buffers 16 32k;

        location / {
            fastcgi_pass unix:__RUN__/php/php-fpm.sock;
            fastcgi_param SCRIPT_FILENAME $document_root/index.php;
            fastcgi_param SCRIPT_NAME     /index.php;
            fastcgi_param REQUEST_URI     $request_uri;
            fastcgi_param QUERY_STRING    $query_string;
            fastcgi_param REQUEST_METHOD  $request_method;
            fastcgi_param CONTENT_TYPE    $content_type;
            fastcgi_param CONTENT_LENGTH  $content_length;
            fastcgi_param SERVER_PROTOCOL $server_protocol;
            fastcgi_param GATEWAY_INTERFACE CGI/1.1;
            fastcgi_param REMOTE_ADDR     $remote_addr;
            fastcgi_param SERVER_NAME     $server_name;
            fastcgi_param SERVER_PORT     $server_port;
        }
    }
}
