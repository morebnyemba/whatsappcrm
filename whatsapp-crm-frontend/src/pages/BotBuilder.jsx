// src/pages/BotBuilderPage.jsx (containing BotBuilderUI)
import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react'; // Make sure useRef is imported
import { ReactFlowProvider, useReactFlow } from 'reactflow';
import { FlowBuilderProvider, useFlowBuilder } from '@/context/FlowBuilderContext';
import FlowHeader from '@/components/bot_builder/FlowHeader';
import FlowSelectorDialog from '@/components/bot_builder/FlowSelectorDialog';
import NodeConfigPanel from '@/components/bot_builder/NodeConfigPanel';
import ReactFlow, { Background, Controls, MiniMap, Panel } from 'reactflow';
import { FiLoader } from 'react-icons/fi';

import * as nodeFile from '@/components/bot_builder/nodes';
const allNodeTypes = {
    message: nodeFile.MessageNode,
    condition: nodeFile.ConditionNode,
    action: nodeFile.ActionNode,
    start: nodeFile.StartNode,
    end: nodeFile.EndNode
};

function BotBuilderUI() {
  const {
    nodes, edges, onNodesChange, onEdgesChange, onConnect,
    flowMetadata, setFlowMetadata,
    availableFlows, isFlowListLoading,
    isLoadingFlow, loadFlow, // loadFlow will now receive reactFlowInstance as an argument
    isSaving, saveFlow,
    // addNodeToCanvas is from context, but we'll call it with dimensions
    addNodeToCanvas: contextAddNode, // Rename to avoid confusion
    selectedNodeForConfigPanel, setSelectedNodeForConfigPanel,
    updateNodeData,
    // flowWrapperRef is NO LONGER taken from context here
  } = useFlowBuilder();

  const reactFlowInstance = useReactFlow();
  const flowWrapperRef = useRef(null); // <<<< DEFINE flowWrapperRef HERE

  useEffect(() => {
      if (reactFlowInstance && nodes.length > 0 && !isLoadingFlow) {
          setTimeout(() => reactFlowInstance.fitView(), 50);
      }
  }, [nodes, isLoadingFlow, reactFlowInstance]);

  const handleMetadataChange = (field, value) => {
    setFlowMetadata(prev => ({ ...prev, [field]: value }));
  };
  
  // Pass reactFlowInstance to loadFlow which is defined in context
  const handleLoadFlow = (flowId) => {
    if (loadFlow) { // Ensure loadFlow from context is defined
        loadFlow(flowId, reactFlowInstance);
    }
  };

  // This function will be passed to FlowHeader, which needs the dimensions
  const handleAddNodeWithDimensions = (type) => {
    const parentWidth = flowWrapperRef.current ? flowWrapperRef.current.offsetWidth : 800;
    const parentHeight = flowWrapperRef.current ? flowWrapperRef.current.offsetHeight : 600;
    if (contextAddNode) { // Ensure contextAddNode from context is defined
        contextAddNode(type, { parentWidth, parentHeight });
    }
  };

  if (isFlowListLoading && !availableFlows.length) {
    return <div className="flex items-center justify-center h-full p-6 text-slate-600 dark:text-slate-400"><FiLoader className="animate-spin h-10 w-10 mr-4" /> Loading flows...</div>;
  }
  
  return (
    <>
      <FlowSelectorDialog 
        isOpen={!flowMetadata.id && !isLoadingFlow}
        availableFlows={availableFlows}
        onSelectFlow={(id) => handleLoadFlow(id)}
        onCreateNew={() => handleLoadFlow(null)}
        isLoading={isFlowListLoading}
      />

      {(!flowMetadata.id && !isLoadingFlow && availableFlows.length > 0) ? (
          <div className="flex items-center justify-center h-full p-6">
            <p className="text-slate-600 dark:text-slate-400">Please select a flow to edit or create a new one.</p>
          </div>
      ) : isLoadingFlow ? (
        <div className="flex items-center justify-center h-full p-6 text-slate-600 dark:text-slate-400"><FiLoader className="animate-spin h-10 w-10 mr-4" /> Loading flow data...</div>
      ) : (
        // Attach the ref to this div
        <div ref={flowWrapperRef} className="h-[calc(100vh-var(--header-height,6rem)-2rem)] flex flex-col border dark:border-slate-700 rounded-xl shadow-lg overflow-hidden bg-white dark:bg-slate-900">
          <FlowHeader
            flowMetadata={flowMetadata}
            onMetadataChange={handleMetadataChange}
            onSaveFlow={saveFlow} // saveFlow is from context
            isSaving={isSaving}
            onAddNewNode={handleAddNodeWithDimensions} // <<<< PASS THE NEW HANDLER
            // onShowFlowSelector={() => { /* Your logic here */ }}
          />
          <div className="flex-grow w-full h-full relative">
            <ReactFlow
              nodes={nodes} edges={edges}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
              nodeTypes={allNodeTypes}
              onNodeClick={(event, node) => setSelectedNodeForConfigPanel(node)}
              fitView
              className="bg-dots-pattern dark:bg-dots-pattern-dark"
            >
              <Background variant="dots" gap={16} size={1} className="dark:opacity-20" />
              <Controls className="react-flow__controls-custom" />
              <MiniMap nodeStrokeWidth={3} zoomable pannable className="react_flow__minimap-custom bg-white dark:bg-slate-800 border dark:border-slate-700" />
              {selectedNodeForConfigPanel && (
                <Panel position="top-right" className="mt-16 mr-2 z-10">
                  <NodeConfigPanel
                    key={selectedNodeForConfigPanel.id}
                    node={selectedNodeForConfigPanel}
                    onNodeDataChange={updateNodeData} // updateNodeData is from context
                    onClose={() => setSelectedNodeForConfigPanel(null)}
                  />
                </Panel>
              )}
            </ReactFlow>
          </div>
        </div>
      )}
    </>
  );
}

// The main export for the page, including providers
export default function BotBuilderPage() {
  return (
    <ReactFlowProvider>
      <FlowBuilderProvider> {/* Your custom context for managing builder state */}
        <BotBuilderUI />
      </FlowBuilderProvider>
    </ReactFlowProvider>
  );
}