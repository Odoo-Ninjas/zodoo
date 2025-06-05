--set critical
update ir_cron set active=false;
delete from ir_config_parameter where key='webkit_path';

/*if-table-exists fetchmail_server*/ update ir_mail_server set smtp_host='${TEST_MAIL_HOST}', smtp_user=null, smtp_pass=null, smtp_encryption='none', smtp_port=${TEST_MAIL_SMTP_PORT};
/*if-column-exists fetchmail_server.is_ssl*/ update fetchmail_server set is_ssl=false;
/*if-table-exists fetchmail_server*/ alter table fetchmail_server add column if not exists server_type varchar;
/*if-table-exists fetchmail_server*/ update fetchmail_server set server='${TEST_MAIL_HOST}', port='${TEST_MAIL_IMAP_PORT}', "user"='postmaster', password='postmaster', server_type='imap', is_ssl=false;

delete from ir_config_parameter where key = 'database.enterprise_code';
/*if-column-exists res_users.password_wite_date*/ update res_users set password_write_date = current_date;


--set not-critical

/*if-table-exists caldav_cal*/ update caldav_cal set password = '1';
/*if-column-exists res_users.enable_2fa*/ update res_users set enable_2fa = false;

update res_users set login = 'admin' where id = 2;