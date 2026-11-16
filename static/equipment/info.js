// Toggle the explanation behind each "i" button.
document.addEventListener("click", function (event) {
    var button = event.target.closest(".equipment__info-button");
    if (!button) {
        return;
    }
    var note = document.getElementById(button.getAttribute("aria-controls"));
    if (!note) {
        return;
    }
    var open = note.hidden;
    note.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
});
