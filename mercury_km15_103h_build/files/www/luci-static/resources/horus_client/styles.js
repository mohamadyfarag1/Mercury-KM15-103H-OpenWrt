'use strict';
'require baseclass';
'require dom';

var horus_version = '1.2.161';

return baseclass.extend({
	getStyles: function() {
		return E('link', {
			rel: 'stylesheet',
			href: '/luci-static/resources/horus_client/horus-theme.css?v=' + horus_version
		});
	}
});