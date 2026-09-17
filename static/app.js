// Disables a form's submit button right after it's submitted, so a slow
// page load can't be mistaken for a missed click and cause a double
// submission (e.g. adding the same member or attendance record twice).
document.addEventListener("submit", function (e) {
  if (e.defaultPrevented) return;
  var form = e.target;
  if (!(form instanceof HTMLFormElement)) return;
  form.querySelectorAll('button[type="submit"], button:not([type])').forEach(function (btn) {
    setTimeout(function () {
      btn.disabled = true;
    }, 0);
  });
});
