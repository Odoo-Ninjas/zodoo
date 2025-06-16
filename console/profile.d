. "$HOME/.bashrc"
PATH="$HOME/.local/bin:$HOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
cat /usr/share/welcome.txt
cd /opt/src
. "$HOME/env"

export PS1="\[\e[1;32m\]odoo \[\e[0m\]> "
export ODOO_BIN=/home/odoo/bin/odoo
alias odoo="$ODOO_BIN -p $PROJECT_NAME"