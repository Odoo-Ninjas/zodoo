{% if item.allowed_ips is defined and item.allowed_ips %}
        # --- IP allowlist (virtual_host.allowed_ips) ---
        # Only these networks reach this vhost; everything else gets 403.
        # The ACME location below stays open so certbot can keep renewing.
{% for cidr in item.allowed_ips.replace(';', ',').split(',') %}
{% if cidr.strip() %}
        allow {{ cidr.strip() }};
{% endif %}
{% endfor %}
        deny all;

        location ^~ /.well-known/acme-challenge/ {
            allow all;
            root /var/www/certbot;
        }
        # --- end IP allowlist ---
{% endif %}
