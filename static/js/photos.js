document.querySelectorAll('.photo-card').forEach((card) => {
  card.querySelector('.move-up').addEventListener('click', () => {
    const previous = card.previousElementSibling;
    if (previous) card.parentElement.insertBefore(card, previous);
  });
  card.querySelector('.move-down').addEventListener('click', () => {
    const next = card.nextElementSibling;
    if (next) card.parentElement.insertBefore(next, card);
  });
});
