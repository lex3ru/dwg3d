// Тема до отрисовки, чтобы не мигало. Отдельным файлом, а не встроенным скриптом: встроенные
// запрещает политика безопасности страницы (R-018 п. 1)
try {
  var t = localStorage.getItem("theme");
  var dark = t === "dark" || (t !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  if (dark) document.documentElement.classList.add("dark");
} catch (e) {}
