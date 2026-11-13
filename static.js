(function(){
  // page fade-in
  document.addEventListener('DOMContentLoaded', function(){
    document.querySelectorAll('.page.fade-in').forEach(function(el){
      el.style.opacity = 0;
      requestAnimationFrame(function(){
        el.style.transition = 'opacity .35s ease';
        el.style.opacity = 1;
      });
    });
  });

  // live stock polling
  function refreshStock(){
    var el = document.getElementById('stockCount');
    if(!el) return;
    fetch('/api/live-stock', {credentials:'same-origin'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(d){
        if(!d) return;
        var next = d.total;
        var cur = parseInt(el.textContent, 10) || 0;
        if(next !== cur){
          el.classList.add('pulse');
          el.textContent = next;
          setTimeout(function(){ el.classList.remove('pulse'); }, 1400);
        }
      })
      .catch(function(){});
  }
  if(document.getElementById('stockCount')){
    refreshStock();
    setInterval(refreshStock, 15000);
  }

  // close mobile nav on link click
  document.addEventListener('click', function(e){
    if(e.target.closest('.nav-links a')) document.body.classList.remove('nav-open');
  });

  // smooth in-page link fades
  document.querySelectorAll('a[href^="/"]:not([target])').forEach(function(a){
    a.addEventListener('click', function(ev){
      if(ev.metaKey||ev.ctrlKey||ev.shiftKey) return;
      var page = document.querySelector('.page.fade-in');
      if(!page) return;
      var href = a.getAttribute('href');
      if(href.startsWith('#')) return;
      ev.preventDefault();
      page.style.transition = 'opacity .22s ease';
      page.style.opacity = 0;
      setTimeout(function(){ window.location = href; }, 220);
    });
  });
})();