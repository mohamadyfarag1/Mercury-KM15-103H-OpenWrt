document.addEventListener("DOMContentLoaded", function() {
    // Only show on logged-in pages (LuCI pages usually have a logout link or body class)
    if (document.body.className.indexOf('logged-in') === -1 && !document.querySelector('a[href*="logout"]')) {
        return;
    }

    if (localStorage.getItem('horus_eula_accepted') === '1') {
        return;
    }

    var overlay = document.createElement('div');
    overlay.id = 'horus-welcome-overlay';
    overlay.style.position = 'fixed';
    overlay.style.top = '0';
    overlay.style.left = '0';
    overlay.style.width = '100vw';
    overlay.style.height = '100vh';
    overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.85)';
    overlay.style.zIndex = '999999';
    overlay.style.display = 'flex';
    overlay.style.justifyContent = 'center';
    overlay.style.alignItems = 'center';
    overlay.style.backdropFilter = 'blur(5px)';

    var modal = document.createElement('div');
    modal.style.backgroundColor = '#fff';
    modal.style.borderRadius = '12px';
    modal.style.padding = '30px';
    modal.style.maxWidth = '500px';
    modal.style.width = '90%';
    modal.style.boxShadow = '0 10px 25px rgba(0, 212, 255, 0.3)';
    modal.style.textAlign = 'center';
    modal.style.fontFamily = 'system-ui, -apple-system, sans-serif';
    modal.style.color = '#333';
    modal.dir = 'rtl';

    var logo = document.createElement('img');
    logo.src = '/luci-static/openwrt2020/logo.png';
    logo.style.maxHeight = '80px';
    logo.style.marginBottom = '20px';
    logo.onerror = function() {
        this.src = '/luci-static/bootstrap/logo.svg';
    };

    var title = document.createElement('h2');
    title.innerText = 'أهلاً بك في نظام Horus Networks 🚀';
    title.style.margin = '0 0 15px 0';
    title.style.color = '#008b8b';

    var desc = document.createElement('p');
    desc.innerText = 'تم تطوير هذا النظام خصيصاً ليقدم لك أفضل أداء، استقرار، وسرعة للشبكة اللاسلكية.';
    desc.style.fontSize = '15px';
    desc.style.lineHeight = '1.6';
    desc.style.marginBottom = '20px';

    var termsBox = document.createElement('div');
    termsBox.style.backgroundColor = '#f8f9fa';
    termsBox.style.border = '1px solid #ddd';
    termsBox.style.borderRadius = '6px';
    termsBox.style.padding = '15px';
    termsBox.style.height = '120px';
    termsBox.style.overflowY = 'auto';
    termsBox.style.fontSize = '13px';
    termsBox.style.textAlign = 'right';
    termsBox.style.marginBottom = '20px';
    termsBox.innerHTML = `
        <strong>سياسة الاستخدام (Horus Networks)</strong><br><br>
        1. هذا النظام مقدم ومحمي بحقوق الملكية الفكرية لشركة حورس للشبكات.<br>
        2. يمنع تعديل أو توزيع أو استغلال هذا السوفتوير للأغراض التجارية دون إذن مسبق.<br>
        3. التحديثات يجب أن تتم فقط من خلال ملفات التحديث الرسمية (OTA) المعتمدة بصيغة IPK الموقعة.<br>
        4. الشركة غير مسؤولة عن أي أضرار تنتج عن سوء الاستخدام أو التدخل غير المصرح به في ملفات النظام.
    `;

    var checkboxWrap = document.createElement('label');
    checkboxWrap.style.display = 'flex';
    checkboxWrap.style.alignItems = 'center';
    checkboxWrap.style.justifyContent = 'center';
    checkboxWrap.style.gap = '10px';
    checkboxWrap.style.cursor = 'pointer';
    checkboxWrap.style.marginBottom = '20px';
    checkboxWrap.style.fontSize = '14px';
    checkboxWrap.style.fontWeight = 'bold';
    checkboxWrap.style.color = '#555';

    var checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.id = 'horus-dont-show';
    checkbox.style.width = '18px';
    checkbox.style.height = '18px';
    checkbox.style.cursor = 'pointer';

    var checkLabel = document.createElement('span');
    checkLabel.innerText = 'أوافق على الشروط، ولا تظهر هذه الرسالة مجدداً';

    checkboxWrap.appendChild(checkbox);
    checkboxWrap.appendChild(checkLabel);

    var btn = document.createElement('button');
    btn.innerText = 'دخول للنظام';
    btn.style.backgroundColor = '#008b8b';
    btn.style.color = '#fff';
    btn.style.border = 'none';
    btn.style.padding = '12px 30px';
    btn.style.fontSize = '16px';
    btn.style.fontWeight = 'bold';
    btn.style.borderRadius = '6px';
    btn.style.cursor = 'pointer';
    btn.style.transition = 'background 0.3s';
    
    btn.onmouseover = function() {
        this.style.backgroundColor = '#006666';
    };
    btn.onmouseout = function() {
        this.style.backgroundColor = '#008b8b';
    };

    btn.onclick = function() {
        if (checkbox.checked) {
            localStorage.setItem('horus_eula_accepted', '1');
        }
        overlay.remove();
    };

    modal.appendChild(logo);
    modal.appendChild(title);
    modal.appendChild(desc);
    modal.appendChild(termsBox);
    modal.appendChild(checkboxWrap);
    modal.appendChild(btn);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
});