#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Invoked by /www/cgi-bin/horus_rrm_apply with the raw POST body on stdin.
# Never interpolate request data into a shell string (previous version built
# a Python source string with '''$BODY''' via shell substitution, which let
# anyone on the LAN inject arbitrary Python/shell code through the request
# body's closing-quote sequence).
import sys
import json
import subprocess

sys.path.insert(0, '/usr/lib')
from horus.sys_wifi import get_5g_channel_health


def main():
    try:
        raw = sys.stdin.read().strip()
        data = json.loads(raw) if raw else {}
        new_ch = str(data.get('channel', ''))
        if not new_ch or not new_ch.isdigit():
            print(json.dumps({'status': 'error', 'message': 'Invalid channel'}))
            return

        cur_5g = get_5g_channel_health()
        prev_ch = str(cur_5g.get('channel', '36'))

        with open('/tmp/horus_rrm_prev_ch.txt', 'w') as f:
            f.write(prev_ch)

        out = subprocess.check_output(['uci', 'show', 'wireless'], text=True)
        dev_name = 'radio0'
        for line in out.splitlines():
            if '=wifi-device' in line:
                d = line.split('.')[1].split('=')[0]
                if '1' in d or '5g' in d.lower():
                    dev_name = d
                    break

        subprocess.run(['uci', 'set', f'wireless.{dev_name}.channel={new_ch}'])
        subprocess.run(['uci', 'commit', 'wireless'])
        subprocess.Popen(['wifi', 'reload'])

        print(json.dumps({
            'status': 'ok',
            'new_channel': new_ch,
            'prev_channel': prev_ch,
            'message': f'تم تغيير التردد إلى قناة {new_ch} بنجاح مع تفعيل حماية الأمان.'
        }))
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': str(e)}))


if __name__ == '__main__':
    main()
