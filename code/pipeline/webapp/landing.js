/* T54 首屏着陆页
   程序化气道背景：只用 three.js 代码构建（CatmullRom 曲线 + TubeGeometry + 粒子），
   零外部模型/纹理依赖——公开仓库没有患者 3D 资产，这里也不引用任何病例数据。
   角色入口复用既有 setRole(role, {from}) / applyRole / nasl_role_v1 体系。 */
(function () {
  "use strict";

  var landing = document.getElementById("landing");
  if (!landing) return;

  var canvas = document.getElementById("landing-canvas");
  var cards = Array.prototype.slice.call(landing.querySelectorAll("[data-landing-role]"));
  var brand = document.getElementById("brand-home");
  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  var renderer = null;
  var scene = null;
  var camera = null;
  var group = null;
  var particles = [];
  var particleGeo = null;
  var raf = 0;
  var running = false;
  var lastFrame = 0;
  var clockT = 0;
  var hiding = false;
  var mounted = false;

  /* ---------- 进入 / 返回 ---------- */
  function workbenchNodes() {
    return [
      document.querySelector("header"),
      document.getElementById("role-bar"),
      document.getElementById("tabs"),
      document.querySelector("main")
    ].filter(Boolean);
  }

  function setWorkbenchInert(on) {
    workbenchNodes().forEach(function (el) {
      try {
        if (on) el.setAttribute("inert", "");
        else el.removeAttribute("inert");
      } catch (e) { /* inert 不支持时忽略 */ }
    });
  }

  function enter(roleName) {
    if (hiding) return;
    hiding = true;
    landing.classList.add("is-hiding");
    document.body.classList.remove("landing-open");
    setWorkbenchInert(false);
    try {
      if (typeof window.setRole === "function") {
        window.setRole(roleName, { from: "landing" });
      }
    } catch (e) {
      if (window.console) console.warn("[landing] setRole failed", e);
    }
    window.setTimeout(function () {
      landing.hidden = true;
      landing.setAttribute("aria-hidden", "true");
      stopLoop();
      hiding = false;
    }, 320);
  }

  function show() {
    landing.hidden = false;
    landing.removeAttribute("aria-hidden");
    landing.classList.remove("is-hiding");
    document.body.classList.add("landing-open");
    setWorkbenchInert(true);
    if (mounted) startLoop();
  }

  cards.forEach(function (el) {
    el.addEventListener("click", function (ev) {
      ev.preventDefault();
      enter(el.getAttribute("data-landing-role") || "operator");
    });
  });

  if (brand) {
    brand.setAttribute("title", "返回首页（重新选择使用身份）");
    brand.addEventListener("click", function () { show(); });
    brand.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); show(); }
    });
  }

  /* ---------- three.js 程序化背景 ---------- */
  function webglAvailable() {
    try {
      var probe = document.createElement("canvas");
      return !!(window.WebGLRenderingContext &&
        (probe.getContext("webgl") || probe.getContext("experimental-webgl")));
    } catch (e) {
      return false;
    }
  }

  function addTube(curve, tubular, radius, radial) {
    var geo = new THREE.TubeGeometry(curve, tubular, radius, radial, false);
    var shell = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({
      color: 0x67d5bd,
      transparent: true,
      opacity: 0.16,
      roughness: 0.38,
      metalness: 0.08,
      clearcoat: 0.6,
      clearcoatRoughness: 0.5,
      side: THREE.DoubleSide,
      depthWrite: false
    }));
    var glow = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      color: 0xa9f3e2,
      transparent: true,
      opacity: 0.05,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.DoubleSide
    }));
    group.add(shell);
    group.add(glow);
  }

  function buildScene() {
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(45, 1, 0.1, 60);
    camera.position.set(0, -0.35, 8.6);
    camera.lookAt(0, -0.45, 0);

    group = new THREE.Group();
    group.scale.setScalar(0.82);
    group.position.y = 0.15;
    scene.add(group);

    var mainPts = [
      new THREE.Vector3(0.00, 1.10, 0.00),
      new THREE.Vector3(0.10, 0.25, 0.18),
      new THREE.Vector3(-0.06, -0.70, 0.28),
      new THREE.Vector3(0.12, -1.55, 0.12),
      new THREE.Vector3(0.02, -2.40, -0.12),
      new THREE.Vector3(0.18, -3.20, -0.26),
      new THREE.Vector3(0.02, -4.05, 0.02)
    ];
    var mainCurve = new THREE.CatmullRomCurve3(mainPts, false, "catmullrom", 0.45);
    var leftCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-1.55, 2.85, -0.35),
      new THREE.Vector3(-1.05, 2.15, -0.18),
      new THREE.Vector3(-0.55, 1.55, -0.02),
      new THREE.Vector3(-0.18, 1.24, 0.02),
      mainPts[0].clone()
    ], false, "catmullrom", 0.45);
    var rightCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(1.45, 3.05, 0.30),
      new THREE.Vector3(0.95, 2.30, 0.20),
      new THREE.Vector3(0.50, 1.68, 0.08),
      new THREE.Vector3(0.16, 1.28, 0.03),
      mainPts[0].clone()
    ], false, "catmullrom", 0.45);

    addTube(mainCurve, 160, 0.42, 20);
    addTube(leftCurve, 80, 0.20, 14);
    addTube(rightCurve, 80, 0.20, 14);

    /* 气流粒子：三条曲线共用一组 points，参数按弧长匀速推进。 */
    var specs = [
      { curve: mainCurve, count: 72, speed: 0.055 },
      { curve: leftCurve, count: 24, speed: 0.045 },
      { curve: rightCurve, count: 24, speed: 0.048 }
    ];
    var total = 0;
    specs.forEach(function (s) { total += s.count; });
    var positions = new Float32Array(total * 3);
    var idx = 0;
    specs.forEach(function (s) {
      for (var i = 0; i < s.count; i++) {
        particles.push({
          curve: s.curve,
          speed: s.speed,
          offset: (i + 0.5) / s.count,
          jitter: (Math.random() - 0.5) * 0.06
        });
        positions[idx * 3] = 0;
        positions[idx * 3 + 1] = 0;
        positions[idx * 3 + 2] = 0;
        idx++;
      }
    });
    particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    var points = new THREE.Points(particleGeo, new THREE.PointsMaterial({
      color: 0xaef7e9,
      size: 0.075,
      transparent: true,
      opacity: 0.8,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true
    }));
    group.add(points);

    scene.add(new THREE.HemisphereLight(0x9fd8e8, 0x0b1016, 0.9));
    var key = new THREE.DirectionalLight(0x9ff5e4, 0.7);
    key.position.set(2.5, 4, 5);
    scene.add(key);

    updateParticles(0);
  }

  function updateParticles(t) {
    if (!particleGeo) return;
    var arr = particleGeo.attributes.position.array;
    var p = new THREE.Vector3();
    for (var i = 0; i < particles.length; i++) {
      var spec = particles[i];
      var u = (spec.offset + t * spec.speed) % 1;
      spec.curve.getPointAt(u, p);
      arr[i * 3] = p.x + spec.jitter;
      arr[i * 3 + 1] = p.y;
      arr[i * 3 + 2] = p.z;
    }
    particleGeo.attributes.position.needsUpdate = true;
  }

  function resize() {
    if (!renderer || !camera) return;
    var w = landing.clientWidth || window.innerWidth;
    var h = landing.clientHeight || window.innerHeight;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
    if (reduceMotion) renderer.render(scene, camera);
  }

  function frame() {
    if (!running) return;
    raf = window.requestAnimationFrame(frame);
    var now = performance.now();
    clockT += Math.min(0.1, (now - lastFrame) / 1000 || 0);
    lastFrame = now;

    group.rotation.y = clockT * 0.11;
    group.position.y = 0.15 + Math.sin(clockT * 0.8) * 0.06;
    camera.position.x = Math.sin(clockT * 0.16) * 0.22;
    camera.lookAt(0, -0.45, 0);

    updateParticles(clockT);
    renderer.render(scene, camera);
  }

  function startLoop() {
    if (!renderer || running) return;
    running = true;
    lastFrame = performance.now();
    frame();
  }

  function stopLoop() {
    running = false;
    if (raf) window.cancelAnimationFrame(raf);
    raf = 0;
  }

  function fallback() {
    landing.classList.add("no-webgl");
    if (canvas) canvas.style.display = "none";
  }

  function initThree() {
    if (!window.THREE || !webglAvailable()) { fallback(); return; }
    try {
      renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: true,
        powerPreference: "low-power"
      });
      renderer.setClearColor(0x000000, 0);
      buildScene();
      resize();
      mounted = true;
      if (reduceMotion) {
        /* 静态一帧：保留三分之四视角与初始粒子位置。 */
        group.rotation.y = 0.34;
        updateParticles(0);
        renderer.render(scene, camera);
      } else {
        startLoop();
      }
    } catch (e) {
      if (window.console) console.warn("[landing] WebGL init failed, using CSS fallback", e);
      stopLoop();
      fallback();
    }
  }

  /* ---------- 生命周期 ---------- */
  window.addEventListener("resize", resize);
  document.addEventListener("visibilitychange", function () {
    if (!mounted || reduceMotion || landing.hidden) return;
    if (document.hidden) stopLoop();
    else startLoop();
  });

  function boot() {
    var params = new URLSearchParams(window.location.search);
    var skip = params.get("landing") === "0" ||
      params.get("demo") === "1" ||
      params.get("role") === "patient";

    if (skip) {
      landing.hidden = true;
      landing.setAttribute("aria-hidden", "true");
      document.body.classList.remove("landing-open");
      setWorkbenchInert(false);
      return;
    }

    document.body.classList.add("landing-open");
    setWorkbenchInert(true);
    initThree();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
