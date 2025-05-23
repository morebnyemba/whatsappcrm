// src/components/bot_builder/FlowSelectorDialog.jsx (Conceptual)
import React from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { FiPlus, FiLoader } from 'react-icons/fi';


export default function FlowSelectorDialog({ isOpen, onOpenChange, availableFlows, onSelectFlow, onCreateNew, isLoading }) {
  if (!isOpen) return null;

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md dark:bg-slate-800 dark:text-slate-50">
        <DialogHeader>
          <DialogTitle>Manage Conversational Flows</DialogTitle>
          <DialogDescription>Select an existing flow to edit or create a new one.</DialogDescription>
        </DialogHeader>
        {isLoading ? (
            <div className="flex items-center justify-center h-24"><FiLoader className="animate-spin h-6 w-6" /> Loading...</div>
        ) : (
        <div className="grid gap-4 py-4">
          <Select onValueChange={(value) => value && onSelectFlow(value)} defaultValue="">
            <SelectTrigger className="w-full dark:bg-slate-700 dark:border-slate-600"><SelectValue placeholder="Select a flow to edit..." /></SelectTrigger>
            <SelectContent className="dark:bg-slate-700"><SelectGroup><SelectLabel className="dark:text-slate-400">Available Flows</SelectLabel>
              {availableFlows.length === 0 && <SelectItem value="-" disabled>No flows yet. Create one!</SelectItem>}
              {availableFlows.map(flow => (<SelectItem key={flow.id} value={flow.id.toString()} className="dark:hover:bg-slate-600 dark:focus:bg-slate-600">{flow.name}</SelectItem>))}
            </SelectGroup></SelectContent>
          </Select>
          <Separator className="my-2 dark:bg-slate-700" />
          <Button onClick={onCreateNew} className="w-full bg-green-600 hover:bg-green-700 text-white dark:bg-green-500 dark:hover:bg-green-600"><FiPlus className="mr-2 h-4 w-4" /> Create New Flow</Button>
        </div>
        )}
      </DialogContent>
    </Dialog>
  );
}