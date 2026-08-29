import React, { useEffect, useRef } from 'react';
import { Network, DataSet } from 'vis-network/standalone';

export default function VisGraph({ nodes, edges }) {
  const ref = useRef(null);
  const net = useRef(null);

  useEffect(() => {
    if (!ref.current || !nodes || !nodes.length) return;

    const data = {
      nodes: new DataSet(nodes),
      edges: new DataSet(edges || []),
    };

    const opts = {
      physics: {
        stabilization: { iterations: 120 },
        barnesHut: { gravitationalConstant: -4000, springLength: 95 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 150,
        zoomView: true,
      },
      edges: {
        smooth: { type: 'curvedCW', roundness: 0.2 },
        width: 1.5,
        color: { color: '#34363c', highlight: '#5e6ad2' },
      },
      nodes: {
        shape: 'dot',
        size: 13,
        borderWidth: 2,
        font: { size: 11, color: '#8a8f98' },
      },
    };

    net.current = new Network(ref.current, data, opts);

    return () => {
      if (net.current) {
        net.current.destroy();
        net.current = null;
      }
    };
  }, [nodes, edges]);

  return <div ref={ref} className="graph-canvas" style={{ minHeight: '340px', width: '100%' }} />;
}
