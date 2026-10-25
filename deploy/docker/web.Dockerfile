FROM php:8.4-apache

RUN a2enmod proxy proxy_http headers \
    && a2dissite 000-default \
    && echo "ServerName localhost" > /etc/apache2/conf-available/servername.conf \
    && a2enconf servername

COPY gate /var/www/gate
COPY rescue /var/www/rescue
COPY deploy/docker/apache/web.conf /etc/apache2/sites-available/rbs.conf
RUN a2ensite rbs

EXPOSE 80 8080
