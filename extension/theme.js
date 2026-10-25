try {
  const theme = JSON.parse(localStorage.getItem('air2:theme'));
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
} catch { /* Use the system theme when storage is unavailable. */ }
