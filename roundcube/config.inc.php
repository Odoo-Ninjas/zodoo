<?php
$config['product_name'] = "Odoo Webmailer";
$config['list_cols'] = ['subject', 'status', 'from', 'to', 'date', 'size', 'flag', 'attachment'];
$config['db_dsnw'] = 'sqlite:////rc/roundcubemail.sqlite?mode=0640';
$config['imap_host'] = '__MAIL_SERVER__';
$config['assets_path'] = '/mailer';
$config['use_secure_urls'] = false;
$config['reverse_proxy'] = true;
$config['request_path'] = '/mailer/';

// required to ignore SSL cert. verification
// see: https://bbs.archlinux.org/viewtopic.php?id=187063
$config['imap_conn_options'] = array(
  'ssl' => array(
     'verify_peer'  => false,
     'verify_peer_name' => false,
   ),
);
$config['smtp_conn_options'] = array(
  'ssl' => array(
        'verify_peer'   => false,
        'verify_peer_name' => false,
  ),
);
$config['smtp_user'] = '';
$config['smtp_pass'] = '';
// SMTP server just like IMAP server
$config['smtp_host'] = '__MAIL_SERVER__:25';
$config['support_url'] = 'mailto:marc@itewimmer.de';
$config['log_dir'] = '/rc/logs';
$config['temp_dir'] = '/rc/tmp';
$config['des_key'] = '8VGuiUzzJvRI7VGOZIM4UTvQ';
$config['product_name'] = 'Odoo Mail';
//$config['plugins'] = array('autologon');
$config['plugins'] = array('autologon');
$config['language'] = 'en_US';
$config['enable_installer'] = false;
?>
