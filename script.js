// Header: sombra/blur al hacer scroll
const header = document.getElementById('header');
const onScroll = () => header.classList.toggle('scrolled', window.scrollY > 8);
onScroll();
window.addEventListener('scroll', onScroll, { passive: true });

// Menú móvil
const navToggle = document.getElementById('nav-toggle');
const mobileMenu = document.getElementById('mobile-menu');

navToggle.addEventListener('click', () => {
  const isOpen = navToggle.getAttribute('aria-expanded') === 'true';
  navToggle.setAttribute('aria-expanded', String(!isOpen));
  navToggle.setAttribute('aria-label', isOpen ? 'Abrir menú' : 'Cerrar menú');
  mobileMenu.classList.toggle('open', !isOpen);
});

mobileMenu.querySelectorAll('a').forEach((link) => {
  link.addEventListener('click', () => {
    navToggle.setAttribute('aria-expanded', 'false');
    navToggle.setAttribute('aria-label', 'Abrir menú');
    mobileMenu.classList.remove('open');
  });
});

// Revelado al hacer scroll (mejora progresiva: el contenido es visible por
// defecto; solo se oculta para animar si el navegador soporta IntersectionObserver
// y el usuario no pidió movimiento reducido)
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const revealItems = document.querySelectorAll('.reveal');

if ('IntersectionObserver' in window && !prefersReducedMotion.matches) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15 }
  );
  revealItems.forEach((item) => {
    item.classList.add('reveal-armed');
    observer.observe(item);
  });
}

// Respeta preferencia de movimiento reducido: pausa la animación SVG del hero
const networkSvg = document.querySelector('.network');
if (networkSvg && prefersReducedMotion.matches && typeof networkSvg.pauseAnimations === 'function') {
  networkSvg.pauseAnimations();
}

// Formulario de contacto (sin backend conectado todavía)
const form = document.getElementById('contact-form');
const status = document.getElementById('form-status');

form.addEventListener('submit', (event) => {
  event.preventDefault();

  if (!form.checkValidity()) {
    status.textContent = 'Revisá los campos: falta completar información obligatoria.';
    form.reportValidity();
    return;
  }

  const nombre = document.getElementById('nombre').value.trim();
  status.textContent = `Gracias, ${nombre}. Recibimos tu consulta y te vamos a contactar en menos de 24 horas.`;
  form.reset();
});

// Año dinámico en el footer
document.getElementById('year').textContent = new Date().getFullYear();
