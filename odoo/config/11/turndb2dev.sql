--set critical
update ir_cron set active=false;
delete from ir_config_parameter where key='webkit_path';
update ir_mail_server set smtp_host='${TEST_MAIL_HOST}', smtp_user=null, smtp_pass=null, smtp_encryption='none', smtp_port=${TEST_MAIL_SMTP_PORT};
alter table fetchmail_server add column if not exists type varchar(255);
update fetchmail_server set server='${TEST_MAIL_HOST}', port='${TEST_MAIL_IMAP_PORT}', "user"='postmaster', password='postmaster', type='imap';
delete from ir_config_parameter where key = 'database.enterprise_code';

delete from ir_config_parameter where key = 'report.url';
insert into ir_config_parameter(key, value) values('report.url', 'http://localhost:8069');

--set not-critical

/*if-table-exists caldav_cal*/ update caldav_cal set password = '1';

