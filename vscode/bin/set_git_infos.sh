#!/bin/bash
GIT_USERNAME="$1"
GIT_EMAIL="$2"
REPO_URL="$3"
REPO_AUTH_TYPE="$4"
REPO_KEY="$5"
USER_HOME=$(eval echo ~$USERNAME)
SSHDIR="$USER_HOME/.ssh"

whoami > /tmp/set_git_infos_called
cd "$HOST_SRC_PATH"

git config --global --add safe.directory "$HOST_SRC_PATH"

if [[ -n "$GIT_USERNAME" && -n "$GIT_EMAIL" ]]; then
	echo "Configuring Git user: $GIT_USERNAME <$GIT_EMAIL>"
    git config --global user.email "$GIT_EMAIL"
    git config --global user.name "$GIT_USERNAME"
fi

mkdir -p "$SSHDIR"
chmod 700 "$SSHDIR"

ssh-keyscan github.com >> ~/.ssh/known_hosts

if [[ -n "$REPO_URL" ]]; then
    git remote set-url origin "$REPO_URL"
    if [[ "$repo_url" =~ ^git@([^:]+): ]]; then
        # SSH form: git@host:org/repo.git
        host="${BASH_REMATCH[1]}"
    elif [[ "$repo_url" =~ ^ssh://([^/]+) ]]; then
        # SSH URL with scheme: ssh://user@host[:port]/path
        host_port="${BASH_REMATCH[1]}"
        host="${host_port%%:*}"   # strip port if present
    elif [[ "$repo_url" =~ ^https?://([^/]+) ]]; then
        # HTTPS form: https://host/...
        host="${BASH_REMATCH[1]}"
    else
        echo "Could not parse host from URL: $repo_url" >&2
    fi
    ssh-keyscan $host >> ~/.ssh/known_hosts

fi

if [[ -n "$REPO_KEY" ]]; then
    echo "$REPO_KEY" | base64 -d >> "$SSHDIR/id_rsa"
    chown "$USERNAME:$USERNAME" "$SSHDIR" -R
    chmod 400 "$SSHDIR/id_rsa"
fi

echo "Git user is $GIT_USERNAME"
