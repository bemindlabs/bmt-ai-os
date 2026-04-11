"use client";

import type { TrainingMetricPoint } from "@/lib/api";

interface LossChartProps {
  data: TrainingMetricPoint[];
  width?: number;
  height?: number;
  className?: string;
}

const PADDING = { top: 12, right: 16, bottom: 32, left: 48 };

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function LossChart({
  data,
  width = 600,
  height = 220,
  className,
}: LossChartProps) {
  if (data.length === 0) {
    return (
      <div
        className={`flex items-center justify-center text-xs text-muted-foreground ${className ?? ""}`}
        style={{ width, height }}
      >
        No metrics yet
      </div>
    );
  }

  const innerW = width - PADDING.left - PADDING.right;
  const innerH = height - PADDING.top - PADDING.bottom;

  const steps = data.map((d) => d.step);
  const losses = data.map((d) => d.loss);

  const minStep = Math.min(...steps);
  const maxStep = Math.max(...steps);
  const minLoss = Math.min(...losses);
  const maxLoss = Math.max(...losses);

  // Pad loss range slightly so the line isn't flush with the axis
  const lossPad = (maxLoss - minLoss) * 0.08 || 0.01;
  const lossMin = Math.max(0, minLoss - lossPad);
  const lossMax = maxLoss + lossPad;

  const stepRange = maxStep - minStep || 1;
  const lossRange = lossMax - lossMin || 1;

  function toX(step: number): number {
    return PADDING.left + ((step - minStep) / stepRange) * innerW;
  }

  function toY(loss: number): number {
    return PADDING.top + (1 - (loss - lossMin) / lossRange) * innerH;
  }

  // Build SVG polyline points string
  const points = data.map((d) => `${toX(d.step)},${toY(d.loss)}`).join(" ");

  // Y-axis tick labels (4 ticks)
  const yTicks = Array.from({ length: 4 }, (_, i) => {
    const fraction = i / 3;
    const lossVal = lossMax - fraction * lossRange;
    const y = PADDING.top + fraction * innerH;
    return { y, label: lossVal.toFixed(4) };
  });

  // X-axis tick labels (up to 5 ticks)
  const xTickCount = clamp(Math.min(data.length, 5), 2, 5);
  const xTicks = Array.from({ length: xTickCount }, (_, i) => {
    const fraction = i / (xTickCount - 1);
    const stepVal = Math.round(minStep + fraction * stepRange);
    const x = PADDING.left + fraction * innerW;
    return { x, label: String(stepVal) };
  });

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      className={className}
      aria-label="Training loss over steps"
      role="img"
    >
      {/* Grid lines */}
      {yTicks.map(({ y }) => (
        <line
          key={y}
          x1={PADDING.left}
          y1={y}
          x2={PADDING.left + innerW}
          y2={y}
          stroke="currentColor"
          strokeOpacity={0.08}
          strokeWidth={1}
        />
      ))}

      {/* Y-axis labels */}
      {yTicks.map(({ y, label }) => (
        <text
          key={label}
          x={PADDING.left - 6}
          y={y}
          textAnchor="end"
          dominantBaseline="middle"
          fontSize={9}
          fill="currentColor"
          opacity={0.5}
        >
          {label}
        </text>
      ))}

      {/* X-axis labels */}
      {xTicks.map(({ x, label }) => (
        <text
          key={label}
          x={x}
          y={PADDING.top + innerH + 14}
          textAnchor="middle"
          fontSize={9}
          fill="currentColor"
          opacity={0.5}
        >
          {label}
        </text>
      ))}

      {/* X-axis label */}
      <text
        x={PADDING.left + innerW / 2}
        y={height - 2}
        textAnchor="middle"
        fontSize={9}
        fill="currentColor"
        opacity={0.4}
      >
        Step
      </text>

      {/* Gradient fill under the line */}
      <defs>
        <linearGradient id="loss-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.25} />
          <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
        </linearGradient>
      </defs>

      {/* Area fill */}
      {data.length > 1 && (
        <polygon
          points={`${points} ${toX(maxStep)},${PADDING.top + innerH} ${toX(minStep)},${PADDING.top + innerH}`}
          fill="url(#loss-fill)"
        />
      )}

      {/* Loss line */}
      <polyline
        points={points}
        fill="none"
        stroke="#3b82f6"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* Last point dot */}
      {data.length > 0 && (
        <circle
          cx={toX(data[data.length - 1].step)}
          cy={toY(data[data.length - 1].loss)}
          r={3}
          fill="#3b82f6"
        />
      )}
    </svg>
  );
}
