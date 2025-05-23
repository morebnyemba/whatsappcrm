import { FiList, FiSave, FiPlus, FiMessageSquare, FiGitBranch, FiTerminal, FiChevronsRight, FiLoader } from 'react-icons/fi';
// Add any other Fi icons you are using in this specific file.// src/components/bot_builder/FlowHeader.jsx
import React from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
// ******************
// ... other imports like Switch, Label, Tooltip, FiIcons ...
import { Tooltip, TooltipProvider, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
// *******************************
export default function FlowHeader({
  flowMetadata,
  onMetadataChange,
  onSaveFlow,
  isSaving,
  onAddNewNode, // Pass function to add node
  onShowFlowSelector, // Function to open the flow selector dialog
}) {
  return (
    <div className="border-b dark:border-slate-700 p-2.5 flex flex-wrap items-center gap-2 md:gap-3 bg-slate-50 dark:bg-slate-800 text-sm">
      <TooltipProvider delayDuration={300}><Tooltip><TooltipTrigger asChild>
          <Button size="sm" variant="outline" onClick={onShowFlowSelector} className="dark:text-slate-300 dark:border-slate-600 dark:hover:bg-slate-700">
              <FiList className="mr-1.5 h-4 w-4" /> Flows
          </Button></TooltipTrigger><TooltipContent>Select or Create Flow</TooltipContent></Tooltip>
      </TooltipProvider>
      <Input type="text" value={flowMetadata.name} onChange={(e) => onMetadataChange('name', e.target.value)} placeholder="Flow Name" className="h-9 font-medium min-w-[150px] max-w-xs flex-shrink dark:bg-slate-700 dark:border-slate-600" />
      {/* ... Other inputs for description, triggerKeywordsRaw, nlpIntent, isActive Switch ... */}
       <Input type="text" value={flowMetadata.description} onChange={(e) => onMetadataChange('description', e.target.value)} placeholder="Description" className="h-9 flex-grow min-w-[150px] dark:bg-slate-700 dark:border-slate-600" />
        <Input type="text" value={flowMetadata.triggerKeywordsRaw} onChange={(e) => onMetadataChange('triggerKeywordsRaw', e.target.value)} placeholder="Keywords (comma-sep)" className="h-9 min-w-[150px] max-w-xs dark:bg-slate-700 dark:border-slate-600" />
        <Input type="text" value={flowMetadata.nlpIntent} onChange={(e) => onMetadataChange('nlpIntent', e.target.value)} placeholder="NLP Intent (optional)" className="h-9 min-w-[150px] max-w-xs dark:bg-slate-700 dark:border-slate-600" />
        <div className="flex items-center space-x-2 pr-2">
            <Switch id="flow-active" checked={flowMetadata.isActive} onCheckedChange={(checked) => onMetadataChange('isActive', checked)} className="data-[state=checked]:bg-green-500" />
            <Label htmlFor="flow-active" className="dark:text-slate-300 cursor-pointer">Active</Label>
        </div>
      <Separator orientation="vertical" className="h-6 hidden md:block dark:bg-slate-700" />
      <div className="flex gap-1 ml-auto md:ml-0">
        <TooltipProvider delayDuration={300}>
            <Tooltip><TooltipTrigger asChild><Button title="Add Message" size="icon" variant="ghost" className="h-8 w-8 dark:text-slate-300 dark:hover:bg-slate-700" onClick={() => onAddNewNode('message')}><FiMessageSquare className="h-4 w-4 text-green-500" /></Button></TooltipTrigger><TooltipContent>Add Message Node</TooltipContent></Tooltip>
            {/* ... Other Add Node Buttons ... */}
            <Tooltip><TooltipTrigger asChild><Button title="Add Condition Node" size="icon" variant="ghost" className="h-8 w-8 dark:text-slate-300 dark:hover:bg-slate-700" onClick={() => onAddNewNode('condition')}><FiGitBranch className="h-4 w-4 text-yellow-500" /></Button></TooltipTrigger><TooltipContent>Add Condition Node</TooltipContent></Tooltip>
            <Tooltip><TooltipTrigger asChild><Button title="Add Action Node" size="icon" variant="ghost" className="h-8 w-8 dark:text-slate-300 dark:hover:bg-slate-700" onClick={() => onAddNewNode('action')}><FiTerminal className="h-4 w-4 text-purple-500" /></Button></TooltipTrigger><TooltipContent>Add Action Node</TooltipContent></Tooltip>
            <Tooltip><TooltipTrigger asChild><Button title="Add End Node" size="icon" variant="ghost" className="h-8 w-8 dark:text-slate-300 dark:hover:bg-slate-700" onClick={() => onAddNewNode('end')}><FiChevronsRight className="h-4 w-4 text-red-500" /></Button></TooltipTrigger><TooltipContent>Add End Node</TooltipContent></Tooltip>
        </TooltipProvider>
      </div>
      <Button size="sm" className="bg-green-600 hover:bg-green-700 text-white dark:bg-green-500 dark:hover:bg-green-600" onClick={onSaveFlow} disabled={isSaving}>
        {isSaving ? <FiLoader className="mr-2 h-4 w-4 animate-spin" /> : <FiSave className="mr-2 h-4 w-4" />}
        {isSaving ? 'Saving...' : (flowMetadata.id ? 'Save Changes' : 'Create Flow')}
      </Button>
    </div>
  );
}