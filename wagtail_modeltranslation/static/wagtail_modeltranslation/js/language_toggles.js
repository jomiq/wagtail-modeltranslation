document.addEventListener("DOMContentLoaded", (event) => {
    const toggles = document.querySelectorAll("input[type=checkbox][class='locale-picker-checkbox']");
    console.log(toggles)
    toggles.forEach(function (toggle) {
        toggle.addEventListener('change', function () {
            enabledSettings =
                Array.from(toggles) // Convert checkboxes to an array to use filter and map.
                    .filter(i => i.checked) // Use Array.filter to remove unchecked checkboxes.
                    .map(i => i.value) // Use Array.map to extract only the checkbox values from the array of objects.

            console.log(enabledSettings)
        })
    });
});
