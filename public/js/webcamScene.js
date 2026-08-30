/**
 * Fallback "AR-simulation" path used when no WebXR-capable AR device is
 * available (e.g. a laptop). A live webcam feed stands in for camera
 * passthrough; generated objects are composited over it with a Three.js
 * scene. There is no 6DOF SLAM tracking here (that needs real AR hardware
 * we don't have) -- placement uses a fixed-depth ray from the pointer, and
 * objects stay put in screen-relative space rather than world-anchored.
 * The WebXR path in xrScene.js is the spec-correct, world-anchored
 * implementation for devices that support it.
 */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const PLACEMENT_DEPTH = 1.6; // meters, arbitrary fixed distance from viewer
const TARGET_SIZE = 0.4; // meters, normalized max dimension of placed objects

export function createWebcamScene({ videoEl, canvasEl, onObjectsChanged, onPlacingChange }) {
  const renderer = new THREE.WebGLRenderer({ canvas: canvasEl, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, 1, 0.05, 50);

  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.9);
  dirLight.position.set(1, 2, 1.5);
  scene.add(dirLight);

  const reticle = new THREE.Mesh(
    new THREE.RingGeometry(0.03, 0.045, 32).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0x4f7cff, transparent: true, opacity: 0.9 })
  );
  reticle.visible = false;
  scene.add(reticle);

  const loader = new GLTFLoader();
  const objects = new Map(); // id -> { group, label, depth, baseScale }
  let selectedId = null;
  let nextId = 1;

  let pending = null; // { object3D, label, resolve }
  let dragging = false;
  const dragPlane = new THREE.Plane();
  const dragOffset = new THREE.Vector3();

  function resize() {
    const w = canvasEl.clientWidth || window.innerWidth;
    const h = canvasEl.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener("resize", resize);

  function pointerToRay(clientX, clientY) {
    const rect = canvasEl.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(ndc, camera);
    return raycaster;
  }

  function normalize(object3D) {
    const box = new THREE.Box3().setFromObject(object3D);
    const size = new THREE.Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const scale = TARGET_SIZE / maxDim;
    const center = new THREE.Vector3();
    box.getCenter(center);
    object3D.position.x -= center.x;
    object3D.position.z -= center.z;
    object3D.position.y -= box.min.y; // sit on its own base
    const group = new THREE.Group();
    group.add(object3D);
    group.scale.setScalar(scale);
    return group;
  }

  async function beginPlacement(glbUrl, label) {
    const gltf = await loader.loadAsync(glbUrl);
    const group = normalize(gltf.scene);
    return new Promise((resolve) => {
      pending = { group, label, resolve };
      reticle.visible = true;
      onPlacingChange && onPlacingChange(true);
    });
  }

  function cancelPlacement() {
    if (!pending) return;
    pending.resolve(null);
    pending = null;
    reticle.visible = false;
    onPlacingChange && onPlacingChange(false);
  }

  function placeAt(clientX, clientY) {
    const raycaster = pointerToRay(clientX, clientY);
    const point = raycaster.ray.origin.clone().add(
      raycaster.ray.direction.clone().multiplyScalar(PLACEMENT_DEPTH)
    );
    if (!pending) return;
    const { group, label, resolve } = pending;
    group.position.copy(point);
    scene.add(group);
    const id = String(nextId++);
    objects.set(id, { group, label, depth: PLACEMENT_DEPTH, baseScale: group.scale.x });
    pending = null;
    reticle.visible = false;
    onPlacingChange && onPlacingChange(false);
    selectObject(id);
    resolve(id);
    emitObjects();
  }

  function selectObject(id) {
    selectedId = id;
    emitObjects();
  }

  function deleteObject(id) {
    const entry = objects.get(id);
    if (!entry) return;
    scene.remove(entry.group);
    entry.group.traverse((n) => {
      if (n.geometry) n.geometry.dispose();
      if (n.material) {
        (Array.isArray(n.material) ? n.material : [n.material]).forEach((m) => m.dispose());
      }
    });
    objects.delete(id);
    if (selectedId === id) selectedId = null;
    emitObjects();
  }

  function emitObjects() {
    if (!onObjectsChanged) return;
    onObjectsChanged(
      Array.from(objects.entries()).map(([id, o]) => ({ id, label: o.label, selected: id === selectedId }))
    );
  }

  function hitTestObjects(clientX, clientY) {
    const raycaster = pointerToRay(clientX, clientY);
    const groups = Array.from(objects.values()).map((o) => o.group);
    const hits = raycaster.intersectObjects(groups, true);
    if (hits.length === 0) return null;
    let obj = hits[0].object;
    while (obj.parent && obj.parent !== scene) obj = obj.parent;
    for (const [id, entry] of objects.entries()) {
      if (entry.group === obj) return id;
    }
    return null;
  }

  // ---- pointer interaction --------------------------------------------

  canvasEl.addEventListener("pointermove", (e) => {
    if (pending) {
      const raycaster = pointerToRay(e.clientX, e.clientY);
      const point = raycaster.ray.origin.clone().add(
        raycaster.ray.direction.clone().multiplyScalar(PLACEMENT_DEPTH)
      );
      reticle.position.copy(point);
      reticle.lookAt(camera.position);
      return;
    }
    if (dragging && selectedId) {
      const raycaster = pointerToRay(e.clientX, e.clientY);
      const hitPoint = new THREE.Vector3();
      if (raycaster.ray.intersectPlane(dragPlane, hitPoint)) {
        const entry = objects.get(selectedId);
        entry.group.position.copy(hitPoint.add(dragOffset));
      }
    }
  });

  canvasEl.addEventListener("pointerdown", (e) => {
    if (pending) {
      placeAt(e.clientX, e.clientY);
      return;
    }
    const hitId = hitTestObjects(e.clientX, e.clientY);
    if (hitId) {
      selectObject(hitId);
      dragging = true;
      const entry = objects.get(hitId);
      dragPlane.setFromNormalAndCoplanarPoint(
        camera.getWorldDirection(new THREE.Vector3()).negate(),
        entry.group.position
      );
      const raycaster = pointerToRay(e.clientX, e.clientY);
      const hitPoint = new THREE.Vector3();
      raycaster.ray.intersectPlane(dragPlane, hitPoint);
      dragOffset.copy(entry.group.position).sub(hitPoint);
    } else {
      selectObject(null);
    }
  });

  window.addEventListener("pointerup", () => { dragging = false; });

  canvasEl.addEventListener(
    "wheel",
    (e) => {
      if (!selectedId) return;
      e.preventDefault();
      const entry = objects.get(selectedId);
      const factor = Math.exp(-e.deltaY * 0.001);
      const next = THREE.MathUtils.clamp(entry.group.scale.x * factor, entry.baseScale * 0.3, entry.baseScale * 3);
      entry.group.scale.setScalar(next);
    },
    { passive: false }
  );

  // ---- lifecycle ---------------------------------------------------

  async function start() {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user" },
      audio: false,
    });
    videoEl.srcObject = stream;
    await videoEl.play();
    resize();
    renderer.setAnimationLoop(() => renderer.render(scene, camera));
  }

  return {
    start,
    beginPlacement,
    cancelPlacement,
    deleteObject,
    selectObject,
  };
}
