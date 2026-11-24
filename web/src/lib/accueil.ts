// @ts-nocheck
// RLPI · animations de la page d'accueil, reprises telles quelles de la maquette (rlpi-accueil.html).
// mountAccueil(racine) lance les démos quand elles entrent à l'écran (boucle tant qu'elles sont visibles)
// et renvoie une fonction qui arrête tout. Le code reste en JavaScript non typé pour coller à la maquette.

export function mountAccueil(root: HTMLElement): () => void {

  /* Pause entre deux lectures d'une même démo (en ms).
     Toutes les démos rejouent en boucle tant qu'elles sont visibles. */
  var LOOP_PAUSE = 5000;
  var OUT='cubic-bezier(.2,.7,.2,1)', IO='cubic-bezier(.6,0,.3,1)', BACK='cubic-bezier(.3,1.5,.5,1)';
  function eOut(p){return 1-Math.pow(1-p,3)}
  function eIO(p){return p<.5?4*p*p*p:1-Math.pow(-2*p+2,3)/2}
  function lin(p){return p}
  function $(r,s){return r.querySelector(s)}
  function $$(r,s){return Array.prototype.slice.call(r.querySelectorAll(s))}
  function fr1(n){return n.toFixed(1).replace('.',',')}

  /* Mini moteur de timeline : tout ce qui est lancé passe par ici pour pouvoir être annulé. */
  function Ctl(){this.a=[];this.t=[];this.dead=false}
  Ctl.prototype.anim=function(el,kf,o){
    var a=el.animate(kf,Object.assign({duration:400,easing:OUT,fill:'both'},o||{}));
    this.a.push(a); return a;
  };
  Ctl.prototype.at=function(ms,fn){
    var s=this; this.t.push(setTimeout(function(){ if(!s.dead) fn(); },ms));
  };
  Ctl.prototype.tween=function(delay,dur,fn,ease){
    var s=this; ease=ease||eOut;
    this.at(delay,function(){
      var t0=performance.now();
      (function f(now){
        if(s.dead) return;
        var p=Math.min((now-t0)/dur,1); fn(ease(p),p);
        if(p<1) requestAnimationFrame(f);
      })(t0);
    });
  };
  Ctl.prototype.kill=function(){
    this.dead=true;
    this.a.forEach(function(a){a.cancel()});
    this.t.forEach(clearTimeout);
  };
  function count(c,el,from,to,delay,dur,fmt){
    fmt=fmt||Math.round; el.textContent=fmt(from);
    c.tween(delay,dur,function(e){el.textContent=fmt(from+(to-from)*e)});
  }
  function swap(c,el,txt,after){
    el.animate([{opacity:1,transform:'none'},{opacity:0,transform:'translateY(-6px)'}],{duration:170,fill:'forwards'}).onfinish=function(){
      if(c.dead) return;
      el.textContent=txt; if(after) after();
      el.animate([{opacity:0,transform:'translateY(6px)'},{opacity:1,transform:'none'}],{duration:240,easing:OUT,fill:'forwards'});
    };
  }
  function bump(el){ el.animate([{transform:'scale(1.25)'},{transform:'scale(1)'}],{duration:300,easing:BACK}); }

  /* ---------- Pseudos d'exemple, tirés au hasard à chaque chargement ---------- */
  var PSEUDOS=['Kestrel','Polaris','Nyxie','Vantor','Moko','Zephyr_','Brakka','Ilyon','Tarsk','Quillo','Saphe','Orvik','Lumo','Draxen','Pikko','Selvar'];
  var i1=Math.floor(Math.random()*PSEUDOS.length), i2=(i1+1+Math.floor(Math.random()*(PSEUDOS.length-1)))%PSEUDOS.length;
  $$(root,'.ps-me').forEach(function(e){e.textContent=PSEUDOS[i1]});
  $$(root,'.ps-mate').forEach(function(e){e.textContent=PSEUDOS[i2]});

  /* ---------- Remerciements : une entrée par modèle ou outil utilisé ---------- */
  var CREDITS=[
    // Sources : pyproject.toml et métadonnées des paquets installés
    {produit:'subtr-actor',createur:'Ivan Malison (rlrml)',role:'Lit chaque replay image par image : positions, vitesses et boost des six voitures et de la balle. Ses détecteurs repèrent les 50/50, les balles ratées et les passes.',url:'https://github.com/rlrml/subtr-actor'},
    {produit:'ballchasing.com',createur:'ses contributeurs',role:'Héberge les replays publics : tes parties, les matchs RLCS et les parties Supersonic Legend sur lesquels les modèles ont appris.',url:'https://ballchasing.com'},
    {produit:'Les joueurs RLCS et SSL',createur:'ceux qui publient leurs replays',role:'Leurs matchs servent d’étalon : la médiane SSL, et ce que les pros jouent dans une situation proche.',url:''},
    {produit:'python-ballchasing',createur:'Rolv-Arild Braaten',role:'Client Python de l’API ballchasing : recherche et téléchargement des parties.',url:'https://github.com/Rolv-Arild/python-ballchasing'},
    {produit:'LightGBM',createur:'Microsoft et la communauté LightGBM',role:'L’algorithme des modèles de RLPI : valeur de chaque situation et placement attendu.',url:'https://github.com/lightgbm-org/LightGBM'},
    {produit:'scikit-learn',createur:'ses contributeurs',role:'Préparation et évaluation des modèles.',url:'https://scikit-learn.org'},
    {produit:'Polars',createur:'Ritchie Vink',role:'Traite les données image par image de chaque partie.',url:'https://pola.rs'}
  ];
  var ul=$(root,'.credits');
  CREDITS.forEach(function(k){
    var li=document.createElement('li'), wrap=k.url?document.createElement('a'):li;
    if(k.url){ wrap.href=k.url; wrap.target='_blank'; wrap.rel='noopener'; li.appendChild(wrap); }
    var b=document.createElement('b'); b.textContent=k.produit;
    var by=document.createElement('span'); by.className='by'; by.textContent='par '+k.createur;
    var p=document.createElement('p'); p.textContent=k.role;
    wrap.appendChild(b); wrap.appendChild(by); wrap.appendChild(p);
    ul.appendChild(li);
  });

  var DEMOS={

    /* ---------- Hero ---------- */
    hero:function(el,c){
      c.anim(el,[{clipPath:'polygon(0 0,0 0,0 100%,0 100%)'},{clipPath:'polygon(0 0,100% 0,calc(100% - 26px) 100%,0 100%)'}],{duration:750,easing:IO});
      var idx=$(el,'.idx');
      c.anim(idx,[{opacity:0,transform:'translateY(18px)'},{opacity:1,transform:'none'}],{duration:600,delay:300});
      count(c,idx,0,48,350,1200);
      var line=$(el,'.spark .line'); line.style.strokeDashoffset=1;
      c.tween(650,1300,function(e){line.style.strokeDashoffset=1-e},eIO);
      c.anim($(el,'.spark circle'),[{transform:'scale(0)'},{transform:'scale(1)'}],{duration:400,delay:1900,easing:BACK});
      $$(el,'.meter').forEach(function(m,i){
        var d=1000+i*160, b=$(m,'b');
        c.anim($(m,'u'),[{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:900,delay:d});
        count(c,b,0,+b.dataset.v,d,900);
      });
      $$(el,'.trow').forEach(function(r,i){
        var d=1600+i*150, n=$(r,'.num');
        c.anim(r,[{opacity:0,transform:'translateX(-18px)'},{opacity:1,transform:'none'}],{duration:500,delay:d});
        count(c,n,0,+n.dataset.v,d,700);
      });
      return 2600;
    },

    /* ---------- Pipeline ---------- */
    pipe:function(el,c){
      var boxes=$$(el,'.box'), tok=$(el,'.token'), st1=$(el,'.st1'), cnt=$(el,'.cnt'), st3=$(el,'.st3'), scan=$(el,'.scan'), mt=$(el,'.mini-tile');
      var P=el.getBoundingClientRect();
      function ctr(b){var r=b.getBoundingClientRect();return [r.left-P.left+r.width/2-23, r.top-P.top+r.height/2-15]}
      var A=ctr(boxes[0]),B=ctr(boxes[1]),C=ctr(boxes[2]);
      function fly(p,q,delay){
        var vertical=Math.abs(q[1]-p[1])>Math.abs(q[0]-p[0]);
        var mx=(p[0]+q[0])/2+(vertical?40:0), my=(p[1]+q[1])/2-(vertical?0:40);
        function T(x,y,s){return 'translate('+x+'px,'+y+'px) scale('+s+') rotate('+(s<1?-8:0)+'deg)'}
        c.anim(tok,[
          {transform:T(p[0],p[1],0),opacity:0},
          {transform:T(p[0],p[1],1),opacity:1,offset:.15},
          {transform:T(mx,my,1.1),offset:.52},
          {transform:T(q[0],q[1],1),opacity:1,offset:.86},
          {transform:T(q[0],q[1],0),opacity:0}
        ],{duration:1150,delay:delay,easing:'ease-in-out',fill:'none'});
      }
      function flash(box,delay,lime){
        c.anim(box,[{background:lime?'#d4ff3a':'#3a3c43',color:lime?'#17181b':'#ecece7'},{background:'#26282d',color:'#ecece7'}],{duration:900,delay:delay,fill:'none'});
      }
      st1.textContent='En jeu'; cnt.textContent='95'; st3.textContent='En attente';
      c.anim(boxes[0],[{background:'#303238'},{background:'#303238',offset:.85},{background:'#26282d'}],{duration:1300});
      c.anim($(el,'.up i'),[{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:1000,easing:'linear'});
      c.anim(mt,[{opacity:0},{opacity:0}],{duration:1,delay:0,fill:'forwards'});
      c.at(1000,function(){ swap(c,st1,'Terminée'); });
      fly(A,B,1050);
      c.at(2050,function(){ flash(boxes[1],0,false); swap(c,cnt,'96'); });
      fly(B,C,2600);
      c.at(3600,function(){ swap(c,st3,'Analyse…'); });
      c.anim(scan,[{opacity:0},{opacity:1,offset:.1},{opacity:1,offset:.88},{opacity:0}],{duration:1100,delay:3600,fill:'none'});
      $$(scan,'i').forEach(function(b,i){
        c.anim(b,[{transform:'scaleY(.2)'},{transform:'scaleY(1)'},{transform:'scaleY(.2)'}],{duration:320,delay:3600+i*70,iterations:3,easing:'ease-in-out',fill:'none'});
      });
      c.at(4700,function(){ swap(c,st3,'Match noté'); flash(boxes[2],0,true); });
      c.anim(mt,[{opacity:0,transform:'perspective(200px) rotateX(90deg)'},{opacity:1,transform:'none'}],{duration:500,delay:4750,easing:BACK});
      return 6000;
    },

    /* ---------- Ma forme ---------- */
    forme:function(el,c){
      var tiles=$$(el,'.tile'), cards=$$(el,'.card'), ph=$(el,'.phase'), sum=$(el,'.sum'), cap=$(el,'.forme-cap');
      ph.textContent='Résultat du match'; sum.textContent='5 V, 7 D';
      tiles.forEach(function(t,i){
        c.anim(t,[{opacity:0,transform:'translateY(-16px)'},{opacity:1,transform:'none'}],{duration:420,delay:i*70,easing:BACK});
      });
      cards.forEach(function(cd,i){
        c.anim(cd,[{transform:'rotateX(0deg)'},{transform:'rotateX(180deg)'}],{duration:650,delay:1800+i*90,easing:IO});
      });
      c.at(1750,function(){ swap(c,ph,'Note du match'); swap(c,sum,'5 au-dessus de 50'); });
      tiles.forEach(function(t){
        if(t.classList.contains('spot')){
          c.anim($(t,'.ring'),[{opacity:0,transform:'scale(.92)'},{opacity:1,transform:'scale(1)'}],{duration:450,delay:3900,easing:BACK});
          c.anim(t,[{transform:'scale(1)'},{transform:'scale(1.08)'},{transform:'scale(1)'}],{duration:500,delay:3900,fill:'none'});
        } else {
          c.anim(t,[{opacity:1},{opacity:.25}],{duration:450,delay:3800,fill:'forwards'});
        }
      });
      c.anim(cap,[{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'none'}],{duration:450,delay:4200});
      return 6400;
    },

    /* ---------- Matchs ---------- */
    match:function(el,c){
      var tr=$(el,'.mt-track'), ph=$(el,'.ph'), phT=$(ph,'em'), sc=$(el,'.score'), note=$(el,'.mt-note'), pts=$$(el,'.pt');
      var D=[3,0,4,-4,2,0,3,-5,2,0,-24,2,-10,0];
      var xs=pts.map(function(p){return parseFloat(p.style.getPropertyValue('--x'))});
      var ys=pts.map(function(p){return parseFloat(p.style.getPropertyValue('--y'))});
      $$(tr,'.fly').forEach(function(f){f.remove()});
      pts.forEach(function(p){p.style.opacity=0; p.classList.remove('ring2')});
      note.style.opacity=0;
      var score=50; sc.textContent=score; sc.classList.remove('low');
      c.anim(ph,[{left:'0%',opacity:1},{left:'71%',offset:.6},{left:'71%',offset:.74},{left:'100%',opacity:1,offset:.98},{left:'100%',opacity:0}],{duration:6200,delay:300,easing:'linear',fill:'none'});
      var k=0;
      function hit(i){
        var p=pts[i]; p.style.opacity=1;
        p.animate([{transform:'scale(.2)'},{transform:'scale(1.35)',offset:.6},{transform:'scale(1)'}],{duration:380,easing:OUT});
        if(D[i]){
          score+=D[i]; sc.textContent=score; sc.classList.toggle('low',score<50); bump(sc);
          var f=document.createElement('span');
          f.className='fly '+(D[i]>0?'p':'n'); f.textContent=(D[i]>0?'+':'−')+Math.abs(D[i]);
          f.style.left=xs[i]+'%'; f.style.top=ys[i]+'%';
          tr.appendChild(f);
          f.animate([{opacity:0,transform:'translate(-50%,-60%)'},{opacity:1,transform:'translate(-50%,-150%)',offset:.25},{opacity:0,transform:'translate(-50%,-260%)'}],{duration:Math.abs(D[i])>15?1600:900,easing:OUT}).onfinish=function(){f.remove()};
        }
        if(p.classList.contains('big')){
          p.classList.add('ring2');
          c.anim(tr,[{transform:'none'},{transform:'translateX(-7px)'},{transform:'translateX(6px)'},{transform:'translateX(-3px)'},{transform:'none'}],{duration:380,fill:'none'});
          note.style.opacity=1;
          note.animate([{opacity:0,transform:'translateX(10px)'},{opacity:1,transform:'none'}],{duration:350,easing:OUT});
        }
      }
      c.tween(300,6200,function(){
        var x=parseFloat(getComputedStyle(ph).left)/tr.clientWidth*100;
        var s=Math.round(Math.min(x,100)/100*300);
        phT.textContent=Math.floor(s/60)+':'+('0'+s%60).slice(-2);
        while(k<xs.length && xs[k]<=x){ hit(k); k++; }
      },lin);
      c.at(6600,function(){ while(k<xs.length){hit(k);k++;} });
      return 7000;
    },

    /* ---------- Mon jeu ---------- */
    jeu:function(el,c){
      $$(el,'.bar').forEach(function(b,i){
        var d=300+i*380, n=$(b,'.val');
        c.anim($(b,'.fill'),[{transform:'scaleX(0)'},{transform:'scaleX(1.07)',offset:.72},{transform:'scaleX(1)'}],{duration:1000,delay:d});
        count(c,n,0,+n.dataset.v,d,900);
        c.anim($(b,'.ref'),[{opacity:0,transform:'translateY(-14px)'},{opacity:1,transform:'none'}],{duration:420,delay:d+950,easing:BACK});
        c.anim($(b,'.gap'),[{opacity:0,transform:'scaleX(0)'},{opacity:1,transform:'scaleX(1)'}],{duration:500,delay:d+1300});
        c.anim($(b,'.delta'),[{opacity:0,transform:'translateY(8px) scale(.8)'},{opacity:1,transform:'none'}],{duration:380,delay:d+1500,easing:BACK});
      });
      c.anim($(el,'.verdict'),[{opacity:0,transform:'translateX(-10px)'},{opacity:1,transform:'none'}],{duration:500,delay:3000});
      return 3800;
    },

    /* ---------- À travailler ---------- */
    field:function(el,c){
      function q(s){return $(el,s)}
      var you=q('.you'),mate=q('.mate'),ball=q('.ball'),oppB=q('.opp-b'),played=q('.played'),best=q('.best'),
          pM=q('.p-mate'),pB1=q('.p-ball1'),pOB=q('.p-oppb'),pB2=q('.p-ball2'),chip=q('.phase-chip'),an=q('.adq-n');
      function place(g,x,y,a){g.setAttribute('transform','translate('+x.toFixed(1)+' '+y.toFixed(1)+')'+(a==null?'':' rotate('+a.toFixed(1)+')'))}
      function along(path,g,t,noRot){
        var L=path.getTotalLength(), l=Math.max(0,Math.min(1,t))*L, p=path.getPointAtLength(l);
        if(noRot){place(g,p.x,p.y);return}
        var a=path.getPointAtLength(Math.max(0,l-1)), b=path.getPointAtLength(Math.min(L,l+1));
        place(g,p.x,p.y,Math.atan2(b.y-a.y,b.x-a.x)*180/Math.PI);
      }
      function phase(txt,cls){ swap(c,chip,txt,function(){chip.className='phase-chip '+cls}); }
      along(played,you,0); along(pM,mate,0); along(pOB,oppB,0); place(ball,196,80);
      played.style.strokeDashoffset=1; best.style.strokeDashoffset=1;
      chip.textContent='Ce que tu as joué'; chip.className='phase-chip p-played';

      c.tween(300,1200,function(e){ along(played,you,e); played.style.strokeDashoffset=1-e; along(pM,mate,e); },eIO);
      c.anim(q('.burst'),[{opacity:1,transform:'scale(.2)'},{opacity:0,transform:'scale(1.6)'}],{duration:650,delay:1480,fill:'none'});
      c.anim(q('.field'),[{transform:'none'},{transform:'translate(-3px,1px)'},{transform:'translate(3px,-1px)'},{transform:'none'}],{duration:260,delay:1480,fill:'none'});
      c.anim(q('.l-a'),[{opacity:0,transform:'translateY(6px)'},{opacity:1,transform:'none'}],{duration:300,delay:1500,easing:BACK});
      c.tween(1550,850,function(e){ along(pB1,ball,e,true); along(pOB,oppB,e); },eOut);
      c.anim(q('.l-loss'),[{opacity:0},{opacity:1}],{duration:300,delay:2450});
      c.anim(q('.l-a'),[{opacity:1},{opacity:0}],{duration:250,delay:3300,fill:'forwards'});
      c.anim(q('.l-loss'),[{opacity:1},{opacity:0}],{duration:250,delay:3300,fill:'forwards'});

      c.at(3300,function(){ phase('Retour arrière','p-rw'); });
      c.anim(q('.rw'),[{opacity:0},{opacity:1,offset:.15},{opacity:.55,offset:.5},{opacity:1,offset:.8},{opacity:0}],{duration:950,delay:3300,fill:'none'});
      c.tween(3350,800,function(e){ var t=1-e; along(played,you,t); along(pM,mate,t); along(pB1,ball,t,true); along(pOB,oppB,t); },eIO);
      c.anim(played,[{opacity:1},{opacity:.25}],{duration:400,delay:3500,fill:'forwards'});

      c.at(4250,function(){ phase('Ce qui était attendu','p-best'); });
      c.tween(4400,1300,function(e){ along(best,you,e); best.style.strokeDashoffset=1-e; },eIO);
      c.tween(4400,900,function(e){ along(pM,mate,e); },eIO);
      c.tween(5300,750,function(e){ along(pB2,ball,e,true); },eOut);
      c.anim(q('.l-b'),[{opacity:0,transform:'translateY(6px)'},{opacity:1,transform:'none'}],{duration:320,delay:5750,easing:BACK});

      c.anim(q('.adq'),[{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'none'}],{duration:400,delay:6000});
      c.anim(q('.g-val'),[{strokeDashoffset:100},{strokeDashoffset:62}],{duration:1100,delay:6150});
      count(c,an,0,38,6150,1100);
      return 7600;
    },

    /* ---------- Mon trio ---------- */
    trio:function(el,c){
      var rows=el._rows, box=$(el,'.rows'), mid=$(el,'.mid');
      rows.forEach(function(r){box.insertBefore(r,mid)});
      setMode(el,c,'p',true);
      rows.forEach(function(r,i){
        c.anim(r,[{opacity:0,transform:'translateX(-20px)'},{opacity:1,transform:'none'}],{duration:450,delay:i*130});
        c.anim($(r,'.t i'),[{transform:'scaleX(0)'},{transform:'scaleX('+TRIO.p.v[i]/100+')'}],{duration:900,delay:200+i*130,fill:'backwards'});
        var v=$(r,'.v'); count(c,v,0,TRIO.p.v[i],200+i*130,900);
      });
      c.anim(mid,[{opacity:0},{opacity:1}],{duration:400,delay:1200});
      c.at(3000,function(){ setMode(el,c,'r'); });
      c.at(6300,function(){ setMode(el,c,'p'); });
      return 8200;
    },

    /* ---------- Méthode ---------- */
    scale:function(el,c){
      var you=$(el,'.you'), yn=$(you,'b'), band=$(el,'.band'), lab=$(el,'.band-lab'), segs=$$(el,'.segs i');
      segs.forEach(function(s,i){s.className=''});
      lab.textContent='Fourchette sur tes 12 parties : 35 à 62';
      you.style.left='0%'; yn.textContent='0';
      c.tween(200,1900,function(e,p){
        var x=p>=1?48:48-48*Math.exp(-4.5*p)*Math.cos(9.5*p);
        you.style.left=x+'%'; yn.textContent=Math.max(0,Math.round(x));
      },lin);
      c.anim(band,[{opacity:0,transform:'scaleX(0)'},{opacity:1,transform:'scaleX(1)'}],{duration:700,delay:2150,easing:BACK});
      c.anim(lab,[{opacity:0},{opacity:1}],{duration:400,delay:2400});
      segs.slice(0,12).forEach(function(s,i){ c.at(2800+i*70,function(){ s.className='on'; s.animate([{transform:'scaleY(1.8)'},{transform:'none'}],{duration:250}); }); });
      c.at(3900,function(){
        segs.slice(12).forEach(function(s,i){ c.at(i*22,function(){ s.className='ghost'; }); });
        swap(c,lab,'Vers 50 parties, la fourchette se resserre');
      });
      c.anim(band,[{left:'35%',width:'27%'},{left:'44%',width:'9%'}],{duration:900,delay:4100,easing:IO,fill:'forwards'});
      c.at(6200,function(){
        segs.slice(12).forEach(function(s){ s.className=''; });
        swap(c,lab,'Fourchette sur tes 12 parties : 35 à 62');
      });
      c.anim(band,[{left:'44%',width:'9%'},{left:'35%',width:'27%'}],{duration:700,delay:6200,easing:IO,fill:'forwards'});
      return 7000;
    },

    /* ---------- Juger à l'aveugle : trois cartes jugées (bien, pas bien, je ne sais pas) ---------- */
    judge:function(el,c){
      var cards=$$(el,'.jcard'), n=$(el,'.j-n');
      function pos(k){ return 'translateY('+(k*12)+'px) scale('+(1-k*.05)+')'; }
      n.textContent='0';
      cards.forEach(function(cd,k){
        cd.style.transform=pos(k); cd.style.opacity=k<3?1:.6;
        var p=$(cd,'.sc-path'); p.style.strokeDashoffset=1;
      });
      // entrée du paquet
      cards.forEach(function(cd,k){
        c.anim(cd,[{opacity:0,transform:'translateY(40px) scale(.9)'},{opacity:k<3?1:.6,transform:pos(k)}],{duration:500,delay:k*90,easing:BACK,fill:'backwards'});
      });
      var V=[
        {s:'.s-good',b:'.jv-good',out:'translate(130%,-6%) rotate(16deg)'},
        {s:'.s-bad',b:'.jv-bad',out:'translate(-130%,-6%) rotate(-16deg)'},
        {s:'.s-maybe',b:'.jv-maybe',out:'translate(0,-130%) rotate(0deg)'}
      ];
      var t=700;
      V.forEach(function(v,i){
        var cd=cards[i], path=$(cd,'.sc-path');
        // la trajectoire se dessine, puis le verdict tombe
        c.tween(t,900,function(e){ path.style.strokeDashoffset=1-e; },eIO);
        c.anim($(cd,v.s),[{opacity:0,transform:'scale(1.6) rotate(-12deg)'},{opacity:1,transform:'scale(1) rotate(-12deg)'}],{duration:320,delay:t+1100,easing:BACK,fill:'forwards'});
        c.anim($(el,v.b),[{transform:'none',filter:'none'},{transform:'scale(1.12)',filter:'brightness(1.15)',offset:.4},{transform:'none',filter:'none'}],{duration:500,delay:t+1100,fill:'none'});
        c.anim(cd,[{transform:'none',opacity:1},{transform:v.out,opacity:0}],{duration:520,delay:t+1450,easing:'cubic-bezier(.5,0,.8,.4)',fill:'forwards'});
        c.at(t+1700,function(){ swap(c,n,String(i+1)); });
        // les cartes suivantes avancent d'un cran
        cards.slice(i+1).forEach(function(nx,j){
          var k=j+1;
          c.anim(nx,[{transform:pos(k),opacity:k<3?1:.6},{transform:pos(k-1),opacity:1}],{duration:380,delay:t+1650,easing:OUT,fill:'forwards'});
        });
        t+=2200;
      });
      c.tween(t,900,function(e){ $(cards[3],'.sc-path').style.strokeDashoffset=1-e; },eIO);
      return t+1200;
    }
  };

  /* Données de démonstration du trio */
  var TRIO={
    p:{v:[48,48,46],rank:3.7,win:42,wl:'5 V et 7 D'},
    r:{v:[52,41,47],rank:3.1,win:60,wl:'3 V et 2 D'}
  };
  function setMode(el,c,m,instant){
    var d=TRIO[m], rows=el._rows, box=$(el,'.rows'), mid=$(el,'.mid');
    $(el,'.knob').style.transform=m==='r'?'translateX(100%)':'none';
    $$(el,'.sw').forEach(function(b){ var on=b.dataset.m===m; b.classList.toggle('on',on); b.setAttribute('aria-pressed',on); });
    var first=rows.map(function(r){return r.getBoundingClientRect().top});
    rows.forEach(function(r,i){
      var bar=$(r,'.t i'), v=$(r,'.v');
      bar.style.transition=instant?'none':''; bar.style.transform='scaleX('+d.v[i]/100+')';
      if(instant){ v.textContent=d.v[i]; } else { count(c,v,+v.textContent,d.v[i],0,700); }
    });
    var rk=$(el,'.s-rank'), wn=$(el,'.s-win'), wl=$(el,'.s-wl');
    if(instant){ rk.textContent=fr1(d.rank); wn.textContent=d.win; wl.textContent=d.wl; }
    else {
      count(c,rk,parseFloat(rk.textContent.replace(',','.')),d.rank,0,700,fr1);
      count(c,wn,+wn.textContent,d.win,0,700);
      swap(c,wl,d.wl);
    }
    var order=rows.map(function(r,i){return i}).sort(function(a,b){return d.v[b]-d.v[a]||a-b});
    order.forEach(function(i){ box.insertBefore(rows[i],mid); });
    if(!instant){
      rows.forEach(function(r,i){
        var dy=first[i]-r.getBoundingClientRect().top;
        if(Math.abs(dy)>1) r.animate([{transform:'translateY('+dy+'px)'},{transform:'none'}],{duration:650,easing:IO});
      });
    }
  }

  /* ---------- Lecture, boucle, rejouer ---------- */
  function run(el){
    if(el._ctl) el._ctl.kill();
    var c=new Ctl(); el._ctl=c;
    var d=DEMOS[el.dataset.demo](el,c);
    if(!el._manual){
      c.at(d+LOOP_PAUSE,function(){ if(el._dead) return; if(el._vis) run(el); else el._pending=true; });
    }
  }

  var els=$$(root,'[data-demo]');

  // Segments de la jauge de fiabilité
  var segs=$(root,'.segs');
  for(var i=0;i<50;i++){ var s=document.createElement('i'); if(i<12) s.className='on'; segs.appendChild(s); }

  // Trio : lignes d'origine + interrupteur cliquable
  var trio=$(root,'[data-demo="trio"]');
  trio._rows=$$(trio,'.row');
  $$(trio,'.sw').forEach(function(b){
    b.addEventListener('click',function(){
      if(trio._ctl) trio._ctl.kill();
      var c=new Ctl(); trio._ctl=c; trio._manual=true;
      setMode(trio,c,b.dataset.m);
    });
  });

  // Bouton « Rejouer »
  els.forEach(function(el){
    if(!el.hasAttribute('data-replay')) return;
    var b=document.createElement('button');
    b.type='button'; b.className='replay-btn'; b.textContent='Rejouer';
    b.addEventListener('click',function(){ el._manual=false; run(el); });
    el.appendChild(b);
  });

  function cleanup(){ els.forEach(function(el){ if(el._ctl) el._ctl.kill(); el._dead=true; }); if(io) io.disconnect(); }
  var io=null;
  if(!('IntersectionObserver' in window) || !Element.prototype.animate){
    return cleanup; // état final statique
  }
  io=new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      var el=e.target;
      if(e.isIntersecting){
        el._vis=true;
        if(!el._ran || el._pending){ el._ran=true; el._pending=false; run(el); }
      } else el._vis=false;
    });
  },{threshold:.3});
  els.forEach(function(el){ io.observe(el); });
  return cleanup;
}
