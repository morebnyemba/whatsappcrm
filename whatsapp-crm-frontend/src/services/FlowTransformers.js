// src/services/flowTransformers.js
import { v4 as uuidv4 } from 'uuid';
// makeNodeInitialData will now be a local helper or part of FlowBuilderContext
// For now, assuming `makeNodeInitialData` is available or node data is structured simply in this example.

// This function will be passed the `makeNodeInitialData` from the context or BotBuilderUI
export const transformBackendToReactFlow = (flowData, backendSteps, backendTransitions, makeNodeInitialDataFn) => {
  if (!flowData) return { flowMetadata: null, nodes: [], edges: [] };

  const metadata = {
    id: flowData.id,
    name: flowData.name || 'Untitled Flow',
    description: flowData.description || '',
    triggerKeywordsRaw: (flowData.trigger_keywords || []).join(', '),
    nlpIntent: flowData.nlp_trigger_intent || '',
    isActive: flowData.is_active !== undefined ? flowData.is_active : true,
  };

  // Scenario 1: Backend provides raw ReactFlow JSON (simplest for frontend loading)
  if (flowData._reactflow_nodes && flowData._reactflow_edges) {
    const loadedNodes = flowData._reactflow_nodes.map(node => ({
      ...node,
      data: makeNodeInitialDataFn(node.data || {}, node.id), // Ensure onChange is attached via makeNodeInitialData
    }));
    return { flowMetadata: metadata, nodes: loadedNodes, edges: flowData._reactflow_edges || [] };
  }

  // Scenario 2: Transform structured backendSteps and backendTransitions
  // This is a placeholder and needs detailed implementation based on your exact model structure.
  // You'd need to fetch steps and transitions separately or ensure they are nested in flowData.
  console.warn("transformBackendToReactFlow: Using placeholder transformation. Implement fully based on your backend model structure if not using _reactflow_nodes/_reactflow_edges.");
  
  const reactFlowNodes = (backendSteps || []).map(step => ({
    id: step.id.toString(),
    type: mapBackendStepTypeToFrontend(step.step_type),
    position: { x: step.position_x || Math.random() * 500, y: step.position_y || Math.random() * 200 },
    data: makeNodeInitialDataFn({ name: step.name, config: step.config || {} }, step.id.toString()),
    draggable: mapBackendStepTypeToFrontend(step.step_type) !== 'start',
  }));

  const reactFlowEdges = (backendTransitions || []).map(trans => ({
    id: `edge-${trans.id}`,
    source: trans.current_step.toString(), // Assuming these are IDs
    target: trans.next_step.toString(),   // Assuming these are IDs
    // TODO: Derive sourceHandle from trans.condition_config for 'condition' nodes
    sourceHandle: trans.source_handle_id || null, 
    animated: true,
    type: 'smoothstep',
    style: { stroke: '#10B981', strokeWidth: 2 },
  }));
  
  // Ensure there's a start node if none are loaded from structured data
  if (!reactFlowNodes.some(n => n.type === 'start')) {
      reactFlowNodes.unshift({ id: 'start-node', type: 'start', position: { x: 50, y: 150 }, data: makeNodeInitialDataFn({}, 'start-node'), draggable: true });
  }

  return { flowMetadata: metadata, nodes: reactFlowNodes, edges: reactFlowEdges };
};

// Helper to map backend step_type to frontend node type
const mapBackendStepTypeToFrontend = (backendStepType) => {
  const mapping = {
    'send_message': 'message',
    'condition': 'condition',
    'action': 'action',
    'start_flow_node': 'start',
    'end_flow': 'end',
    // Add other mappings as needed
  };
  return mapping[backendStepType] || 'default'; // Fallback to a default node type
};


export const transformFrontendToBackendPayload = (flowMetadata, nodes, edges) => {
  // CRITICAL: This function transforms ReactFlow state into the payload your backend API expects.
  // This example continues to assume you might send raw _reactflow_nodes and _reactflow_edges
  // as per your original handleSaveFlow function.
  // If your backend expects structured steps and transitions, you need complex mapping here.
  
  // Remove onChange from node data before saving
  const sanitizedNodes = nodes.map(n => {
    const { onChange, ...restOfData } = n.data;
    return { ...n, data: restOfData };
  });

  return {
    name: flowMetadata.name,
    description: flowMetadata.description,
    is_active: flowMetadata.isActive,
    trigger_keywords: flowMetadata.triggerKeywordsRaw.split(',').map(k => k.trim()).filter(k => k),
    nlp_trigger_intent: flowMetadata.nlpIntent || null,
    _reactflow_nodes: sanitizedNodes, // Sending raw ReactFlow data
    _reactflow_edges: edges,         // Sending raw ReactFlow data
    // If your backend expects structured steps/transitions derived from nodes/edges:
    // steps: transformNodesToBackendSteps(nodes),
    // transitions: transformEdgesToBackendTransitions(edges, mapOfClientNodeIdToBackendStepId),
  };
};