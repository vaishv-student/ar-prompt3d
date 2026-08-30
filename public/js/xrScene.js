/**
 * Real WebXR AR path (hit-test + world-anchored placement) for devices
 * that actually support immersive-ar (e.g. an ARCore Android phone in
 * Chrome). Not exercised on hardware during development -- no AR-capable
 * device was available -- but follows the standard WebXR hit-test pattern
 * (as in three.js's own webxr_ar_hittest example) so it is spec-correct
 * and ready to demo on a supported device. The webcam fallback in
 * webcamScene.js is the path actually verified end-to-end.
 */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const TARGET_SIZE = 0.4;

export async function isXRSupported() {
  if (!navigator.xr) return false;
  try {
    return await navigator.xr.isSessionSupported("immersive-ar");
  } catch {
    return false;
  }
}

export function createXRScene({ canvasEl, onObjectsChanged, onPlacingChange }) {
  const renderer = new THREE.WebGLRenderer({ canvas: canvasEl, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.xr.enabled = true;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera();

  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.9);
  dirLight.position.set(1, 2, 1.5);
  scene.add(dirLight);

  const reticle = new THREE.Mesh(
    new THREE.RingGeometry(0.06, 0.09, 32).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0x4f7cff })
  );
  reticle.matrixAutoUpdate = false;
  reticle.visible = false;
  scene.add(reticle);

  const loader = new GLTFLoader();
  const objects = new Map();
  let nextId = 1;
  let pending = null;
  let hitTestSource = null;
  let session = null;

  function fixVertexColorMaterials(object3D) {
    // See webcamScene.js's copy of this function for why: Shap-E meshes
    // carry vertex colour but no material, so GLTFLoader's spec-default
    // material (fully metallic) renders them near-black without an
    // environment map.
    object3D.traverse((node) => {
      if (!node.isMesh || !node.material) return;
      const mats = Array.isArray(node.material) ? node.material : [node.material];
      for (const mat of mats) {
        if (mat.isMeshStandardMaterial) {
          mat.metalness = 0;
          mat.roughness = 1;
          if (node.geometry.attributes.color) mat.vertexColors = true;
          mat.needsUpdate = true;
        }
      }
    });
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
    object3D.position.y -= box.min.y;
    const group = new THREE.Group();
    group.add(object3D);
    group.scale.setScalar(scale);
    return group;
  }

  async function beginPlacement(glbUrl, label) {
    const gltf = await loader.loadAsync(glbUrl);
    fixVertexColorMaterials(gltf.scene);
    const group = normalize(gltf.scene);
    return new Promise((resolve) => {
      pending = { group, label, resolve };
      onPlacingChange && onPlacingChange(true);
    });
  }

  function emitObjects() {
    onObjectsChanged &&
      onObjectsChanged(Array.from(objects.entries()).map(([id, o]) => ({ id, label: o.label, selected: false })));
  }

  function deleteObject(id) {
    const entry = objects.get(id);
    if (!entry) return;
    scene.remove(entry.group);
    objects.delete(id);
    emitObjects();
  }

  function onSelect() {
    if (!pending || !reticle.visible) return;
    const { group, label, resolve } = pending;
    group.position.setFromMatrixPosition(reticle.matrix);
    group.quaternion.setFromRotationMatrix(reticle.matrix);
    scene.add(group);
    const id = String(nextId++);
    objects.set(id, { group, label });
    pending = null;
    onPlacingChange && onPlacingChange(false);
    resolve(id);
    emitObjects();
  }

  async function enter() {
    session = await navigator.xr.requestSession("immersive-ar", {
      requiredFeatures: ["hit-test"],
    });
    renderer.xr.setReferenceSpaceType("local");
    await renderer.xr.setSession(session);
    session.addEventListener("select", onSelect);

    const viewerSpace = await session.requestReferenceSpace("viewer");
    hitTestSource = await session.requestHitTestSource({ space: viewerSpace });

    renderer.setAnimationLoop((timestamp, frame) => {
      if (frame && hitTestSource) {
        const referenceSpace = renderer.xr.getReferenceSpace();
        const results = frame.getHitTestResults(hitTestSource);
        if (results.length > 0) {
          const pose = results[0].getPose(referenceSpace);
          reticle.visible = true;
          reticle.matrix.fromArray(pose.transform.matrix);
        } else {
          reticle.visible = false;
        }
      }
      renderer.render(scene, camera);
    });
  }

  return { enter, beginPlacement, deleteObject };
}
