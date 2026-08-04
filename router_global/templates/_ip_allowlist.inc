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
{% if item.allowlist_public_paths is defined and item.allowlist_public_paths %}
        # Pfade, die trotz Allowlist offen bleiben muessen -- etwa eine API, die
        # von Kundenmaschinen aus dem Internet erreichbar sein muss. Sie
        # authentifizieren sich selbst; die Allowlist waere dort eine Sperre,
        # kein Schutz.
{% for path in item.allowlist_public_paths.replace(';', ',').split(',') %}
{% if path.strip() %}
        location ^~ {{ path.strip() }} {
            allow all;
            proxy_pass http://{{ item.upstream_name }};
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            client_max_body_size 1024M;
        }
{% endif %}
{% endfor %}
{% endif %}
        # --- end IP allowlist ---
{% endif %}
