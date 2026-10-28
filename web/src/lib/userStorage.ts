// Данные в браузере, которые принадлежат человеку, а не устройству: черновик плана, очередь
// отметок инвентаризации, фоновые задачи (R-018 п. 4). Ключ — с id вошедшего: на общем
// компьютере другой пользователь их не увидит и не отправит от своего имени. При выходе они не
// чистятся — неотправленное дождётся, когда тот же человек войдёт снова. Настройки вида (тема,
// слои, столбцы реестра) — общие для устройства.

let user = "";

// Вошедший — его задаёт MeProvider до отрисовки страниц
export function setStorageUser(id: string) {
  user = id;
}

export function userKey(key: string): string {
  const own = `${key}@${user}`;
  try {
    // данные прежней версии — без пользователя: достаются первому вошедшему, как и было
    const legacy = localStorage.getItem(key);
    if (legacy !== null) {
      if (localStorage.getItem(own) === null) localStorage.setItem(own, legacy);
      localStorage.removeItem(key);
    }
  } catch {
    /* хранилище недоступно — ключ всё равно свой */
  }
  return own;
}
