
sudo nano /etc/asterisk/extensions.conf

Save (Ctrl+O, Enter, Ctrl+X in nano), then reload:

sudo asterisk -rx "dialplan reload"

Confirm it updated:

sudo asterisk -rx "dialplan show 7000@internal"