document.addEventListener("DOMContentLoaded", (event) => {
    const toggles = document.querySelectorAll("input[type=checkbox][class='locale-picker-checkbox']");
    if (toggles.length > 0) {
        console.log(toggles);
        let cookie = Object();
        init_cookie = readCookie()

        toggles.forEach(function (toggle) {

            if (toggle.id in init_cookie) {
                toggle.checked = init_cookie[toggle.id];
            }
            cookie[toggle.id] = toggle.checked;

            toggle.addEventListener('change', (event) => {
                let c = readCookie()
                c[event.target.id] = event.target.checked;
                setCookie(c);
            });
        });
        setCookie(cookie);
    }
});

function readCookie() {
    res = JSON.parse(localStorage.getItem("wagtail_modeltranslation_toggles"));
    console.log("read: ", res);
    return res ? res : Object();
}

function setCookie(value) {
    console.log("setCookie:", value);
    localStorage.setItem("wagtail_modeltranslation_toggles", JSON.stringify(value));
}