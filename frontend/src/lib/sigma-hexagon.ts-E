/**
 * NodeHexagonProgram: custom Sigma v3 WebGL node program that renders hexagons.
 *
 * Extends NodeCircleProgram (which handles processVisibleItem and setUniforms)
 * and overrides getDefinition() to substitute a hexagon SDF fragment shader
 * for the default circle fragment shader.
 *
 * The hexagon SDF uses flat-top orientation:
 *   max(|p.x| * 0.866 + |p.y| * 0.5, |p.y|) - r
 *
 * Used in Viz.tsx for COMPONENT nodes (S136: diagram-derived nodes).
 */
import { NodeCircleProgram } from "sigma/rendering"

// Vertex shader: identical to NodeCircleProgram (passes diffVector and radius to fragment)
const VERTEX_SHADER_SOURCE = `
attribute vec4 a_id;
attribute vec4 a_color;
attribute vec2 a_position;
attribute float a_size;
attribute float a_angle;

uniform mat3 u_matrix;
uniform float u_sizeRatio;
uniform float u_correctionRatio;

varying vec4 v_color;
varying vec2 v_diffVector;
varying float v_radius;

const float bias = 255.0 / 254.0;

void main() {
  float size = a_size * u_correctionRatio / u_sizeRatio * 4.0;
  vec2 diffVector = size * vec2(cos(a_angle), sin(a_angle));
  vec2 position = a_position + diffVector;
  gl_Position = vec4(
    (u_matrix * vec3(position, 1)).xy,
    0,
    1
  );
  v_diffVector = diffVector;
  v_radius = size / 2.0;

  #ifdef PICKING_MODE
  v_color = a_id;
  #else
  v_color = a_color;
  #endif

  v_color.a *= bias;
}
`

// Fragment shader: uses hexagon SDF instead of circle distance
// hexDist returns positive outside hexagon, negative inside
const FRAGMENT_SHADER_SOURCE = `
precision highp float;

varying vec4 v_color;
varying vec2 v_diffVector;
varying float v_radius;

uniform float u_correctionRatio;

const vec4 transparent = vec4(0.0, 0.0, 0.0, 0.0);

float hexDist(vec2 p, float r) {
  vec2 q = abs(p);
  return max(q.x * 0.866025 + q.y * 0.5, q.y) - r;
}

void main(void) {
  float border = u_correctionRatio * 2.0;
  float dist = hexDist(v_diffVector, v_radius - border);

  #ifdef PICKING_MODE
  if (dist > border)
    gl_FragColor = transparent;
  else
    gl_FragColor = v_color;

  #else
  float t = 0.0;
  if (dist > border)
    t = 1.0;
  else if (dist > 0.0)
    t = dist / border;

  gl_FragColor = mix(v_color, transparent, t);
  #endif
}
`

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- sigma generic variance requires any cast
export default class NodeHexagonProgram extends (NodeCircleProgram as any) {
  static ANGLE_1 = 0
  static ANGLE_2 = (2 * Math.PI) / 3
  static ANGLE_3 = (4 * Math.PI) / 3

  getDefinition() {
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call -- base class dynamic
    const base = super.getDefinition() as Record<string, unknown>
    return {
      ...base,
      VERTEX_SHADER_SOURCE,
      FRAGMENT_SHADER_SOURCE,
    }
  }
}
