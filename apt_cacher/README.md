This Docker container creates an instance of squid-deb-proxy that listens
for `apt` connections on port 8002, and caches the packages.

Several third party repositories are configured in the ACL, in addition to
official repositories.

## Server Deployment

### Using Docker Compose

Build the image and run the container locally.

```
docker-compose up
```

### Using Docker Swarm Mode

Build the image.

```
docker build -t squid-deb-proxy .
```

Deploy the container to the swarm.

```
docker stack deploy -c docker-compose.yml debcache
```

## Client Configuration

Configure `apt` on clients to use the proxy by specifying it in the
`/etc/apt/apt.conf.d/00squidproxy` file.

```
# /etc/apt/apt.conf.d/00squidproxy

Acquire {
  Retries "0";
  HTTP { Proxy "http://<proxy IP>:<proxy port>"; };
};
```
