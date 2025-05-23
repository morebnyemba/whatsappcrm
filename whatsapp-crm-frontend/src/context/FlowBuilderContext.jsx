// src/context/FlowBuilderContext.jsx
import React, {
    createContext,
    useContext,
    useState,
    useCallback,
    useEffect,
    useMemo
} from 'react';
import {
    applyNodeChanges,
    applyEdgeChanges,
    addEdge,
} from 'reactflow';
import { v4 as uuidv4 } from 'uuid';
import { toast } from 'sonner'; // Assuming you use sonner for toasts

// --- API Configuration ---
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
const getAuthToken = () => localStorage.getItem('accessToken'); // Replace with your actual auth logic

// --- API Helper Function ---
async function apiCall(endpoint, method = 'GET', body = null) {
    const token = getAuthToken();
    const headers = {
        ...(token && { 'Authorization': `Bearer ${token}` }),
        ...(!body || !(body instanceof FormData) && { 'Content-Type': 'application/json' }),
    };
    const config = {
        method,
        headers,
        ...(body && { body: (body instanceof FormData) ? body : JSON.stringify(body) }),
    };

    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);

    if (!response.ok) {
        let errorData;
        try {
            errorData = await response.json();
        } catch (e) {
            errorData = { detail: response.statusText || `Request failed with status ${response.status}` };
        }
        console.error("API Error:", response.status, errorData);
        let errorMessage = errorData.detail || `API request failed: ${response.status}`;
        if (typeof errorData === 'object' && errorData !== null && !errorData.detail && Object.keys(errorData).length > 0) {
            errorMessage = Object.entries(errorData).map(([key, value]) =>
                `${key}: ${Array.isArray(value) ? value.join(', ') : String(value)}`
            ).join('; ');
        }
        const err = new Error(errorMessage);
        err.response = response;
        err.data = errorData;
        throw err;
    }
    if (response.status === 204 || response.headers.get("content-length") === "0") {
        return null;
    }
    return await response.json();
}
// --- End API Helper ---

const FlowBuilderContext = createContext(null);

export const useFlowBuilder = () => {
    const context = useContext(FlowBuilderContext);
    if (!context) {
        throw new Error("useFlowBuilder must be used within a FlowBuilderProvider");
    }
    return context;
};

export const FlowBuilderProvider = ({ children }) => {
    // Core React Flow state
    const [nodes, setNodes] = useState([]);
    const [edges, setEdges] = useState([]);

    // Flow metadata state
    const [flowMetadata, setFlowMetadata] = useState({
        id: null,
        name: 'Untitled Flow',
        description: '',
        triggerKeywordsRaw: '',
        nlpIntent: '',
        isActive: true,
    });

    // State for managing available flows and UI
    const [availableFlows, setAvailableFlows] = useState([]);
    const [showFlowSelectorDialog, setShowFlowSelectorDialog] = useState(true);

    // Loading and Saving states
    const [isFlowListLoading, setIsLoadingFlowListLoading] = useState(true);
    const [isLoadingFlow, setIsLoadingFlow] = useState(false);
    const [isSaving, setIsSaving] = useState(false);

    // UI interaction state
    const [selectedNodeForConfigPanel, setSelectedNodeForConfigPanel] = useState(null);

    // --- React Flow Event Handlers ---
    const onNodesChange = useCallback((changes) => setNodes((nds) => applyNodeChanges(changes, nds)), [setNodes]);
    const onEdgesChange = useCallback((changes) => setEdges((eds) => applyEdgeChanges(changes, eds)), [setEdges]);
    const onConnect = useCallback(
        (connection) => {
            const newEdge = {
                ...connection,
                id: uuidv4(),
                animated: true,
                type: 'smoothstep', // Or your preferred edge type
                style: { stroke: '#10B981', strokeWidth: 2 }
            };
            setEdges((eds) => addEdge(newEdge, eds));
        },
        [setEdges]
    );

    // --- Node Data Management ---
    const updateNodeData = useCallback((nodeId, fieldOrData, value) => {
        setNodes((nds) =>
            nds.map((n) => {
                if (n.id === nodeId) {
                    const nodeDataUpdates = typeof fieldOrData === 'string'
                        ? { [fieldOrData]: value }
                        : fieldOrData;
                    const updatedData = { ...n.data, ...nodeDataUpdates };
                    // Ensure onChange is preserved if it was part of the original data structure
                    if (n.data && typeof n.data.onChange === 'function' && !updatedData.onChange) {
                        updatedData.onChange = n.data.onChange;
                    }
                    return { ...n, data: updatedData };
                }
                return n;
            })
        );
    }, [setNodes]);

    const makeNodeInitialData = useCallback((initialSpecificData = {}) => {
        return {
            ...initialSpecificData,
            onChange: updateNodeData,
        };
    }, [updateNodeData]);


    // --- Flow Actions ---
    const fetchFlowsFromAPI = useCallback(async () => {
        setIsLoadingFlowListLoading(true);
        try {
            const data = await apiCall('/automation/flows/');
            setAvailableFlows(data.results || data || []);
        } catch (error) {
            toast.error(`Error fetching flows: ${error.message}`);
            setAvailableFlows([]);
        } finally {
            setIsLoadingFlowListLoading(false);
        }
    }, []); // No dependencies as setters are stable

    useEffect(() => {
        fetchFlowsFromAPI();
    }, [fetchFlowsFromAPI]);


    const loadFlow = useCallback(async (selectedFlowId, reactFlowInstanceForFitView) => {
        setShowFlowSelectorDialog(false);
        setSelectedNodeForConfigPanel(null); // Clear any selected node
        if (!selectedFlowId) { // Create New Flow
            setFlowMetadata({
                id: null, name: 'Untitled New Flow', description: '',
                triggerKeywordsRaw: '', nlpIntent: '', isActive: true,
            });
            setNodes([{ id: 'start-node', type: 'start', position: { x: 50, y: 150 }, data: makeNodeInitialData({ name: 'Start' }), draggable: true }]);
            setEdges([]);
            setIsLoadingFlow(false); // Not loading, it's a new setup
            if (reactFlowInstanceForFitView) setTimeout(() => reactFlowInstanceForFitView.fitView(), 50);
            toast.info("New flow initialized. Configure and save.");
            return;
        }

        setIsLoadingFlow(true);
        try {
            const flowDataFromAPI = await apiCall(`/automation/flows/${selectedFlowId}/`);
            setFlowMetadata({
                id: flowDataFromAPI.id,
                name: flowDataFromAPI.name || 'Untitled Flow',
                description: flowDataFromAPI.description || '',
                triggerKeywordsRaw: (flowDataFromAPI.trigger_keywords || []).join(', '),
                nlpIntent: flowDataFromAPI.nlp_trigger_intent || '',
                isActive: flowDataFromAPI.is_active !== undefined ? flowDataFromAPI.is_active : true,
            });

            if (flowDataFromAPI._reactflow_nodes && flowDataFromAPI._reactflow_edges) {
                const loadedNodes = flowDataFromAPI._reactflow_nodes.map(node => ({
                    ...node,
                    data: makeNodeInitialData(node.data),
                }));
                setNodes(loadedNodes);
                setEdges(flowDataFromAPI._reactflow_edges);
            } else {
                // TODO: Implement transformation from your structured backend models
                toast.warning("Flow layout loaded. If backend doesn't store raw ReactFlow JSON, step/transition transformation from models is needed here.");
                const defaultStartNode = { id: 'start-node', type: 'start', position: { x: 50, y: 150 }, data: makeNodeInitialData({ name: 'Start' }), draggable: true };
                setNodes([defaultStartNode]);
                setEdges([]);
            }
            toast.success(`Loaded flow: ${flowDataFromAPI.name}`);
        } catch (error) {
            toast.error(`Error loading flow: ${error.message}`);
            setShowFlowSelectorDialog(true); // Re-show selector on load error
        } finally {
            setIsLoadingFlow(false);
            if (reactFlowInstanceForFitView) setTimeout(() => reactFlowInstanceForFitView.fitView(), 50);
        }
    }, [makeNodeInitialData]); // Removed setters from deps as they are stable


    const addNodeToCanvas = useCallback((type, dimensions) => {
        const { parentWidth = 800, parentHeight = 600 } = dimensions || {};
        if (type === 'start' && nodes.some(n => n.type === 'start')) {
            toast.error("A Start node already exists."); return;
        }
        const defaultNodeData =
            type === 'message' ? { name: 'New Message', config: { message_type: 'text', text: { body: 'Hello!' } } } :
            type === 'condition' ? { name: 'New Condition', config: { condition_logic: 'true' } } :
            type === 'action' ? { name: 'New Action', config: { actions_to_run: [] } } :
            type === 'end' ? { name: 'End Flow' } :
            { name: 'Start' };

        const newNode = {
            id: uuidv4(), type,
            position: {
                x: Math.max(20, Math.random() * (parentWidth * 0.5)),
                y: Math.max(20, Math.random() * (parentHeight * 0.5))
            },
            data: makeNodeInitialData(defaultNodeData),
        };
        setNodes((nds) => nds.concat(newNode));
    }, [nodes, makeNodeInitialData]); // Removed setNodes from deps


    const saveFlow = useCallback(async (reactFlowInstanceToSave) => {
        setIsSaving(true);
        const currentNodes = reactFlowInstanceToSave ? reactFlowInstanceToSave.getNodes() : nodes;
        const currentEdges = reactFlowInstanceToSave ? reactFlowInstanceToSave.getEdges() : edges;

        const startNodes = currentNodes.filter(node => node.type === 'start');
        if (startNodes.length === 0) { toast.error("Flow must have a Start node."); setIsSaving(false); return; }
        if (startNodes.length > 1) { toast.error("Flow can only have one Start node."); setIsSaving(false); return; }

        const payload = {
            name: flowMetadata.name,
            description: flowMetadata.description,
            is_active: flowMetadata.isActive,
            trigger_keywords: flowMetadata.triggerKeywordsRaw.split(',').map(k => k.trim()).filter(k => k),
            nlp_trigger_intent: flowMetadata.nlpIntent || null,
            _reactflow_nodes: currentNodes.map(n => {
                const { onChange, ...restOfData } = n.data || {}; // Remove onChange from data before saving
                return { ...n, data: restOfData };
            }),
            _reactflow_edges: currentEdges,
        };

        const method = flowMetadata.id ? 'PUT' : 'POST';
        const endpoint = flowMetadata.id ? `/automation/flows/${flowMetadata.id}/` : '/automation/flows/';

        try {
            const savedFlow = await apiCall(endpoint, method, payload);
            setFlowMetadata(prev => ({
                ...prev,
                id: savedFlow.id, name: savedFlow.name, description: savedFlow.description,
                triggerKeywordsRaw: (savedFlow.trigger_keywords || []).join(', '),
                nlpIntent: savedFlow.nlp_trigger_intent || '', isActive: savedFlow.is_active,
            }));
            setAvailableFlows(prevFlows => {
                const existing = prevFlows.find(f => f.id === savedFlow.id);
                if (existing) {
                    return prevFlows.map(f => f.id === savedFlow.id ? savedFlow : f).sort((a,b) => a.name.localeCompare(b.name));
                }
                return [savedFlow, ...prevFlows].sort((a,b) => a.name.localeCompare(b.name));
            });
            if (savedFlow._reactflow_nodes && savedFlow._reactflow_edges) { // If backend returns updated canvas data
                const loadedNodes = savedFlow._reactflow_nodes.map(node => ({
                    ...node, data: makeNodeInitialData(node.data),
                }));
                setNodes(loadedNodes); setEdges(savedFlow._reactflow_edges);
            }
            toast.success(`Flow "${savedFlow.name}" saved successfully!`);
        } catch (error) {
            toast.error(`Save failed: ${error.message || 'Unknown error'}`);
        } finally {
            setIsSaving(false);
        }
    }, [flowMetadata, nodes, edges, makeNodeInitialData]); // Removed setters from deps

    // Memoize context value to prevent unnecessary re-renders of consumers
    const contextValue = useMemo(() => ({
        nodes, setNodes, // Expose setters if children need to manipulate directly (less common)
        edges, setEdges,
        onNodesChange,
        onEdgesChange,
        onConnect,
        flowMetadata, setFlowMetadata,
        availableFlows, setAvailableFlows,
        isFlowListLoading, setIsLoadingFlowListLoading,
        isLoadingFlow, setIsLoadingFlow,
        isSaving, setIsSaving,
        selectedNodeForConfigPanel, setSelectedNodeForConfigPanel,
        showFlowSelectorDialog, setShowFlowSelectorDialog,
        loadFlow,
        saveFlow,
        addNodeToCanvas,
        updateNodeData,
        makeNodeInitialData, // Export if custom nodes are defined outside this context
        fetchFlowsFromAPI,
    }), [
        nodes, edges, onNodesChange, onEdgesChange, onConnect,
        flowMetadata, availableFlows, isFlowListLoading, isLoadingFlow, isSaving,
        selectedNodeForConfigPanel, showFlowSelectorDialog, // State values
        setNodes, setEdges, setFlowMetadata, setAvailableFlows, // State setters
        setIsLoadingFlowListLoading, setIsLoadingFlow, setIsSaving,
        setSelectedNodeForConfigPanel, setShowFlowSelectorDialog, // State setters
        loadFlow, saveFlow, addNodeToCanvas, updateNodeData, makeNodeInitialData, fetchFlowsFromAPI // Memoized callbacks
    ]);

    return (
        <FlowBuilderContext.Provider value={contextValue}>
            {children}
        </FlowBuilderContext.Provider>
    );
};