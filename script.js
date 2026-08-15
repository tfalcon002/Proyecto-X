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

// Formulario de contacto: envío por AJAX a Formspree, sin salir de la página
const form = document.getElementById('contact-form');
const status = document.getElementById('form-status');
const submitButton = form.querySelector('.form-submit');

form.addEventListener('submit', async (event) => {
  event.preventDefault();

  if (!form.checkValidity()) {
    status.textContent = 'Revisa los campos: falta completar información obligatoria.';
    form.reportValidity();
    return;
  }

  const nombre = document.getElementById('nombre').value.trim();
  submitButton.disabled = true;
  status.textContent = 'Enviando...';

  try {
    const response = await fetch(form.action, {
      method: form.method,
      body: new FormData(form),
      headers: { Accept: 'application/json' },
    });

    if (response.ok) {
      status.textContent = `Gracias, ${nombre}. Recibimos tu consulta y te vamos a contactar en menos de 24 horas.`;
      form.reset();
    } else {
      status.textContent = 'No pudimos enviar tu consulta. Intenta nuevamente o escríbenos por WhatsApp.';
    }
  } catch (error) {
    status.textContent = 'No pudimos enviar tu consulta. Revisa tu conexión e intenta nuevamente.';
  } finally {
    submitButton.disabled = false;
  }
});

// Año dinámico en el footer
document.getElementById('year').textContent = new Date().getFullYear();
