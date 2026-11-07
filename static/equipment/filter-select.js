// Narrow a <select>'s options as the user types in a search box.
// <input data-filter-select="<select id>">
document.addEventListener("input", function (event) {
    var input = event.target.closest("[data-filter-select]");
    if (!input) {
        return;
    }
    var select = document.getElementById(input.getAttribute("data-filter-select"));
    if (!select) {
        return;
    }
    var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    Array.prototype.forEach.call(select.options, function (option) {
        var text = option.text.toLowerCase();
        // Keep the blank choice, "other" and the current selection visible.
        var keep = option.value === "" || option.value === "other" || option.selected;
        var match = words.every(function (word) { return text.indexOf(word) !== -1; });
        option.hidden = !(keep || match);
        option.disabled = !(keep || match);
    });
});
