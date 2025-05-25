// src/pages/ContactsPage.jsx
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar';
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { FiUserPlus, FiEdit, FiTrash2, FiSearch, FiChevronDown, FiChevronUp, FiPlusCircle, FiStar, FiTrendingUp, FiTag, FiLoader, FiAlertCircle, FiPhone, FiMail, FiMapPin, FiBriefcase, FiCalendar, FiUsers, FiInfo, FiEdit3, FiToggleLeft, FiToggleRight, FiFilter, FiSave } from 'react-icons/fi';
import { format, parseISO, isValid } from 'date-fns';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuCheckboxItem, DropdownMenuLabel, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from 'sonner';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from '@/components/ui/skeleton';

// --- API Configuration & Helper (Should be in a shared service file) ---
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const getAuthToken = () => localStorage.getItem('accessToken');

// It's highly recommended to move apiCall to src/services/api.js and import it.
async function apiCall(endpoint, method = 'GET', body = null, isPaginatedFallback = false, includeAuth = true) {
    const token = includeAuth ? getAuthToken() : null;
    const headers = {
        ...(!body || !(body instanceof FormData) && { 'Content-Type': 'application/json' }),
        ...(token && { 'Authorization': `Bearer ${token}` }),
    };
    const config = {
        method,
        headers,
        ...(body && (body instanceof FormData ? { body } : { body: JSON.stringify(body) })),
    };

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
        if (!response.ok) {
            let errorData = { detail: `Request to ${endpoint} failed: ${response.status} ${response.statusText}` };
            try {
                const contentType = response.headers.get("content-type");
                if (contentType && contentType.indexOf("application/json") !== -1) {
                    errorData = await response.json();
                } else {
                    const text = await response.text();
                    if (text) errorData.detail = text;
                }
            } catch (e) { console.error("Failed to parse error response:", e); }

            const errorMessage = errorData.detail ||
                (typeof errorData === 'object' && errorData !== null && !errorData.detail ?
                    Object.entries(errorData).map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(', ') : String(v)}`).join('; ') :
                    `API Error ${response.status}`);
            const err = new Error(errorMessage);
            err.data = errorData;
            err.isApiError = true;
            throw err;
        }
        if (response.status === 204 || (response.headers.get("content-length") || "0") === "0") {
            return isPaginatedFallback ? { results: [], count: 0, next: null, previous: null } : null;
        }
        const data = await response.json();
        return isPaginatedFallback ? {
            results: data.results || (Array.isArray(data) ? data : []),
            count: data.count === undefined ? (Array.isArray(data) ? data.length : 0) : data.count,
            next: data.next,
            previous: data.previous
        } : data;
    } catch (error) {
        console.error(`API call to ${method} ${API_BASE_URL}${endpoint} failed:`, error);
        if (!error.isApiError || !error.message.includes("(toasted)")) {
            toast.error(error.message || 'An API error occurred. Check console.');
            error.message = (error.message || "") + " (toasted)";
        }
        throw error;
    }
}


const contactFormSchema = z.object({
    name: z.string().min(1, "Name is required").max(255),
    whatsapp_id: z.string().min(1, "WhatsApp ID is required").max(50), // Usually not editable after creation
    email: z.string().email("Invalid email address").or(z.literal('')).nullable(),
    phone_number: z.string().max(20).or(z.literal('')).nullable(), // Assuming max 20 for display
    address: z.string().max(255).or(z.literal('')).nullable(),
    city: z.string().max(100).or(z.literal('')).nullable(),
    country: z.string().max(100).or(z.literal('')).nullable(),
    date_of_birth: z.string().nullable().refine(val => val === null || val === '' || !isNaN(Date.parse(val)), { message: "Invalid date" }),
    gender: z.string().max(50).or(z.literal('')).nullable(),
    occupation: z.string().max(100).or(z.literal('')).nullable(),
    industry: z.string().max(100).or(z.literal('')).nullable(),
    company_name: z.string().max(255).or(z.literal('')).nullable(),
    company_size: z.string().max(50).or(z.literal('')).nullable(), // Or number if you have specific ranges
    company_website: z.string().url("Invalid URL").or(z.literal('')).nullable(),
    lead_status: z.string().max(50).or(z.literal('')).nullable(),
    acquisition_source: z.string().max(100).or(z.literal('')).nullable(), // Changed from lead_source
    interest_level: z.string().max(50).or(z.literal('')).nullable(), // Or number
    preferred_contact_method: z.string().max(50).or(z.literal('')).nullable(),
    communication_frequency: z.string().max(50).or(z.literal('')).nullable(),
    notes: z.string().or(z.literal('')).nullable(),
    is_blocked: z.boolean().default(false),
    needs_human_intervention: z.boolean().default(false),
    // tags are handled separately
});


const ProfileFieldDisplay = ({ icon, label, value, type = "text", children }) => {
    const IconComponent = icon;
    let displayValue = value;
    if (type === "date" && value) {
        const parsedDate = parseISO(value);
        if (isValid(parsedDate)) {
            displayValue = format(parsedDate, "MMMM d, yyyy");
        } else {
            displayValue = "N/A";
        }
    } else if (type === "boolean") {
        displayValue = value ? "Yes" : "No";
    } else if (value === null || value === undefined || value === '') {
        displayValue = "N/A";
    }


    return (
        <div className="mb-3 text-sm">
            <dt className="flex items-center text-slate-500 dark:text-slate-400">
                {IconComponent && <IconComponent className="mr-2 h-4 w-4 text-slate-400" />}
                {label}
            </dt>
            <dd className="mt-1 font-medium text-slate-700 dark:text-slate-200">
                {children || displayValue}
            </dd>
        </div>
    );
};


const DataTable = ({ columns, data, isLoading, onRowClick, selectedRowId }) => {
    if (isLoading && data.length === 0) {
        return (
            <div className="space-y-2 p-4">
                {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
        );
    }
    if (!data.length && !isLoading) {
        return <div className="p-4 text-center text-slate-500 dark:text-slate-400">No contacts found.</div>;
    }

    return (
        <div className="overflow-x-auto">
            <Table>
                <TableHeader>
                    <TableRow>
                        {columns.map((column) => (
                            <TableHead key={column.accessorKey} className="whitespace-nowrap">
                                {column.header}
                            </TableHead>
                        ))}
                        <TableHead>Actions</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {data.map((row) => (
                        <TableRow
                            key={row.id}
                            onClick={() => onRowClick(row.id)}
                            className={`cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 ${selectedRowId === row.id ? 'bg-slate-100 dark:bg-slate-700/50' : ''}`}
                        >
                            {columns.map((column) => {
                                let cellValue = column.accessorKey.split('.').reduce((acc, part) => acc && acc[part], row);
                                if (column.cell) {
                                    cellValue = column.cell({ row });
                                } else if (column.accessorKey === 'is_blocked' || column.accessorKey === 'needs_human_intervention') {
                                    cellValue = cellValue ? <Badge variant="destructive">Yes</Badge> : <Badge variant="outline">No</Badge>;
                                } else if (column.accessorKey === 'customer_profile.tags') {
                                     // customer_profile not available in list view from ContactSerializer, so tags will be empty
                                     // This will render an empty cell or you can show 'N/A'
                                     cellValue = Array.isArray(cellValue) && cellValue.length > 0 ? cellValue.join(', ') : 'N/A';
                                } else if (column.accessorKey === 'last_seen' && cellValue) {
                                    const parsedDate = parseISO(cellValue);
                                    cellValue = isValid(parsedDate) ? format(parsedDate, "PPpp") : "Invalid Date";
                                } else if (cellValue === null || cellValue === undefined) {
                                    cellValue = "N/A";
                                }
                                return <TableCell key={column.accessorKey} className="whitespace-nowrap">{cellValue}</TableCell>;
                            })}
                            <TableCell className="whitespace-nowrap">
                                {/* Actions like Edit/Delete can be added here if needed directly in row,
                                   but selection leading to side panel is the current pattern */}
                                <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); onRowClick(row.id); /* Could also open edit dialog directly */ }}>
                                    View
                                </Button>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    );
};

export default function ContactsPage() {
    const [contacts, setContacts] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [selectedContact, setSelectedContact] = useState(null);
    const [isFetchingDetail, setIsFetchingDetail] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');
    const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 10 });
    const [pageCount, setPageCount] = useState(0);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingContact, setEditingContact] = useState(null);

    const [existingTags, setExistingTags] = useState([]); // For tag input
    const [newTag, setNewTag] = useState('');
    const [currentContactTags, setCurrentContactTags] = useState([]);

    const { register, handleSubmit, reset, formState: { errors }, control, setValue, watch } = useForm({
        resolver: zodResolver(contactFormSchema),
        defaultValues: {
            name: '',
            whatsapp_id: '',
            email: '',
            phone_number: '',
            address: '',
            city: '',
            country: '',
            date_of_birth: null,
            gender: '',
            occupation: '',
            industry: '',
            company_name: '',
            company_size: '',
            company_website: '',
            lead_status: '',
            acquisition_source: '', // Updated field
            interest_level: '',
            preferred_contact_method: '',
            communication_frequency: '',
            notes: '',
            is_blocked: false,
            needs_human_intervention: false,
        }
    });
    
    const watchedIsBlocked = watch('is_blocked');
    const watchedNeedsIntervention = watch('needs_human_intervention');


    const fetchContacts = useCallback(async (page = 1, search = '') => {
        setIsLoading(true);
        try {
            const endpoint = `/crm-api/conversations/contacts/?page=${page}&search=${encodeURIComponent(search)}`;
            const data = await apiCall(endpoint, 'GET', null, true);
            setContacts(data.results || []);
            setPageCount(Math.ceil((data.count || 0) / pagination.pageSize));
        } catch (error) {
            // toast handled by apiCall
        } finally {
            setIsLoading(false);
        }
    }, [pagination.pageSize]);

    useEffect(() => {
        fetchContacts(pagination.pageIndex + 1, searchTerm);
    }, [fetchContacts, pagination.pageIndex, searchTerm]);

    const handleSelectContact = async (contactId) => {
        if (selectedContact?.id === contactId) { // Toggle off if same contact is clicked
            setSelectedContact(null);
            return;
        }
        setIsFetchingDetail(true);
        setSelectedContact(null); // Clear previous before fetching new
        try {
            const data = await apiCall(`/crm-api/customer-data/profiles/${contactId}/`); // Fetches using ContactDetailSerializer
            setSelectedContact(data);
        } catch (error) {
            toast.error("Failed to fetch contact details.");
        } finally {
            setIsFetchingDetail(false);
        }
    };
    
    const handleOpenEditModal = (contactData) => {
        setEditingContact(contactData);
        const profile = contactData.customer_profile || {};
        reset({
            name: contactData.name || '',
            whatsapp_id: contactData.whatsapp_id || '', // Usually not editable
            email: profile.email || '',
            phone_number: profile.phone_number || '',
            address: profile.address || '',
            city: profile.city || '',
            country: profile.country || '',
            date_of_birth: profile.date_of_birth ? format(parseISO(profile.date_of_birth), 'yyyy-MM-dd') : '',
            gender: profile.gender || '',
            occupation: profile.occupation || '',
            industry: profile.industry || '',
            company_name: profile.company_name || '',
            company_size: profile.company_size || '',
            company_website: profile.company_website || '',
            lead_status: profile.lead_status || '',
            acquisition_source: profile.acquisition_source || '', // Use acquisition_source
            interest_level: profile.interest_level || '',
            preferred_contact_method: profile.preferred_contact_method || '',
            communication_frequency: profile.communication_frequency || '',
            notes: profile.notes || '',
            is_blocked: contactData.is_blocked || false,
            needs_human_intervention: contactData.needs_human_intervention || false,
        });
        setCurrentContactTags(profile.tags || []);
        // Potentially fetch all existing tags for suggestions if needed
        // setExistingTags(/* fetch all unique tags from system */);
        setIsModalOpen(true);
    };


    const onSubmit = async (formData) => {
        if (!editingContact) return;
        setIsSubmitting(true);

        const contactPayload = {
            name: formData.name,
            is_blocked: formData.is_blocked,
            needs_human_intervention: formData.needs_human_intervention,
        };
        // Remove undefined keys to prevent sending them if not changed
        Object.keys(contactPayload).forEach(key => contactPayload[key] === undefined && delete contactPayload[key]);

        const profilePayload = {
            email: formData.email,
            phone_number: formData.phone_number,
            address: formData.address,
            city: formData.city,
            country: formData.country,
            date_of_birth: formData.date_of_birth || null,
            gender: formData.gender,
            occupation: formData.occupation,
            industry: formData.industry,
            company_name: formData.company_name,
            company_size: formData.company_size,
            company_website: formData.company_website,
            lead_status: formData.lead_status,
            acquisition_source: formData.acquisition_source, // Use acquisition_source
            interest_level: formData.interest_level,
            preferred_contact_method: formData.preferred_contact_method,
            communication_frequency: formData.communication_frequency,
            notes: formData.notes,
            tags: currentContactTags, // currentContactTags is the updated list of strings
        };
        Object.keys(profilePayload).forEach(key => profilePayload[key] === undefined && delete profilePayload[key]);
        
        try {
            let contactUpdateSuccessful = true;
            // 1. Update contact-specific fields
            if (Object.keys(contactPayload).length > 0) {
                 await apiCall(`/crm-api/contacts/${editingContact.id}/`, 'PATCH', contactPayload);
            }

            // 2. Update customer profile fields
            if (Object.keys(profilePayload).length > 0 && editingContact.id) {
                await apiCall(`/crm-api/customer-profiles/${editingContact.id}/`, 'PATCH', profilePayload);
            }

            toast.success("Contact updated successfully!");
            setIsModalOpen(false);
            setEditingContact(null);
            fetchContacts(pagination.pageIndex + 1, searchTerm); // Refresh list
            if (selectedContact?.id === editingContact.id) { // Refresh detail view if it was selected
                handleSelectContact(editingContact.id);
            }
        } catch (error) {
            // toast is handled by apiCall
            // Optionally, handle specific error scenarios here if needed
        } finally {
            setIsSubmitting(false);
        }
    };


    const handleAddTag = () => {
        if (newTag && !currentContactTags.includes(newTag.trim())) {
            setCurrentContactTags([...currentContactTags, newTag.trim()]);
            setNewTag('');
        }
    };
    const handleRemoveTag = (tagToRemove) => {
        setCurrentContactTags(currentContactTags.filter(tag => tag !== tagToRemove));
    };

    const columns = useMemo(() => [
        { header: 'Name', accessorKey: 'name' },
        { header: 'WhatsApp ID', accessorKey: 'whatsapp_id' },
        { header: 'Blocked', accessorKey: 'is_blocked' },
        { header: 'Needs Attention', accessorKey: 'needs_human_intervention' },
        { header: 'Tags', accessorKey: 'customer_profile.tags' }, // Will be 'N/A' as profile not in list data
        { header: 'Last Seen', accessorKey: 'last_seen' },
    ], []);


    return (
        <div className="flex h-[calc(100vh-var(--header-height,4rem)-2rem)] gap-6 p-1">
            {/* Main Contacts List */}
            <Card className="w-2/3 flex flex-col">
                <CardHeader>
                    <div className="flex justify-between items-center">
                        <div>
                            <CardTitle>Contacts</CardTitle>
                            <CardDescription>Manage your customer contacts.</CardDescription>
                        </div>
                        {/* <Button size="sm" onClick={() => handleOpenEditModal({})}> <FiUserPlus className="mr-2 h-4 w-4" /> Add New Contact </Button> */}
                        {/* Add New Contact might be better as a separate flow if whatsapp_id is key */}
                    </div>
                    <div className="mt-4 relative">
                        <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                        <Input
                            type="search"
                            placeholder="Search contacts by name or WhatsApp ID..."
                            className="pl-9"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                    </div>
                </CardHeader>
                <CardContent className="flex-grow overflow-hidden">
                     <ScrollArea className="h-full">
                        <DataTable
                            columns={columns}
                            data={contacts}
                            isLoading={isLoading}
                            onRowClick={handleSelectContact}
                            selectedRowId={selectedContact?.id}
                        />
                    </ScrollArea>
                </CardContent>
                <div className="p-4 border-t flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
                    <div>Page {pagination.pageIndex + 1} of {pageCount || 1}</div>
                    <div className="space-x-2">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPagination(prev => ({ ...prev, pageIndex: Math.max(0, prev.pageIndex - 1) }))}
                            disabled={pagination.pageIndex === 0 || isLoading}
                        >
                            Previous
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPagination(prev => ({ ...prev, pageIndex: Math.min(pageCount - 1, prev.pageIndex + 1) }))}
                            disabled={pagination.pageIndex >= pageCount - 1 || isLoading}
                        >
                            Next
                        </Button>
                    </div>
                </div>
            </Card>

            {/* Contact Detail Panel */}
            <Card className="w-1/3 flex flex-col">
                <CardHeader className="flex flex-row justify-between items-center">
                    <div>
                        <CardTitle>Contact Details</CardTitle>
                        <CardDescription>View and edit contact information.</CardDescription>
                    </div>
                    {selectedContact && (
                         <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button variant="outline" size="icon" onClick={() => handleOpenEditModal(selectedContact)} disabled={isFetchingDetail}>
                                        <FiEdit3 className="h-4 w-4" />
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent><p>Edit Contact</p></TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    )}
                </CardHeader>
                <ScrollArea className="flex-grow">
                    <CardContent className="p-6">
                        {isFetchingDetail && (
                            <div className="space-y-3">
                                <Skeleton className="h-8 w-3/4" />
                                <Skeleton className="h-4 w-1/2" />
                                <Skeleton className="h-4 w-1/3" />
                                <hr className="my-4"/>
                                <Skeleton className="h-6 w-1/4 mb-2" />
                                <Skeleton className="h-4 w-full" />
                                <Skeleton className="h-4 w-full" />
                                <Skeleton className="h-4 w-3/4" />
                            </div>
                        )}
                        {!isFetchingDetail && selectedContact && (
                            <div>
                                <div className="flex items-center mb-6">
                                    <Avatar className="h-16 w-16 mr-4">
                                        <AvatarImage src={`https://ui-avatars.com/api/?name=${encodeURIComponent(selectedContact.name || selectedContact.whatsapp_id)}&background=random`} />
                                        <AvatarFallback>{(selectedContact.name || selectedContact.whatsapp_id || 'U').substring(0, 2).toUpperCase()}</AvatarFallback>
                                    </Avatar>
                                    <div>
                                        <h2 className="text-xl font-semibold">{selectedContact.name || "N/A"}</h2>
                                        <p className="text-sm text-slate-500 dark:text-slate-400">{selectedContact.whatsapp_id}</p>
                                    </div>
                                </div>

                                <h3 className="text-md font-semibold mb-2 text-slate-700 dark:text-slate-200 border-b pb-1">Contact Info</h3>
                                <ProfileFieldDisplay icon={FiPhone} label="Primary Phone" value={selectedContact.customer_profile?.phone_number} />
                                <ProfileFieldDisplay icon={FiMail} label="Email" value={selectedContact.customer_profile?.email} />
                                <ProfileFieldDisplay icon={FiMapPin} label="Address" value={`${selectedContact.customer_profile?.address || ''} ${selectedContact.customer_profile?.city || ''} ${selectedContact.customer_profile?.country || ''}`.trim() || "N/A"} />
                                
                                <h3 className="text-md font-semibold mt-4 mb-2 text-slate-700 dark:text-slate-200 border-b pb-1">Profile Details</h3>
                                <ProfileFieldDisplay icon={FiCalendar} label="Date of Birth" value={selectedContact.customer_profile?.date_of_birth} type="date" />
                                <ProfileFieldDisplay icon={FiUsers} label="Gender" value={selectedContact.customer_profile?.gender} />
                                <ProfileFieldDisplay icon={FiBriefcase} label="Occupation" value={selectedContact.customer_profile?.occupation} />
                                <ProfileFieldDisplay icon={FiBriefcase} label="Industry" value={selectedContact.customer_profile?.industry} />
                                <ProfileFieldDisplay icon={FiBriefcase} label="Company" value={selectedContact.customer_profile?.company_name} />
                                {/* Update to use acquisition_source */}
                                <ProfileFieldDisplay icon={FiInfo} label="Lead Source" value={selectedContact.customer_profile?.acquisition_source} />
                                <ProfileFieldDisplay icon={FiTrendingUp} label="Lead Status" value={selectedContact.customer_profile?.lead_status} />
                                <ProfileFieldDisplay icon={FiStar} label="Interest Level" value={selectedContact.customer_profile?.interest_level} />
                                

                                <h3 className="text-md font-semibold mt-4 mb-2 text-slate-700 dark:text-slate-200 border-b pb-1">Status & Notes</h3>
                                <ProfileFieldDisplay icon={FiToggleLeft} label="Blocked" value={selectedContact.is_blocked} type="boolean" />
                                <ProfileFieldDisplay icon={FiAlertCircle} label="Needs Human Intervention" value={selectedContact.needs_human_intervention} type="boolean" />
                                <ProfileFieldDisplay icon={FiEdit} label="Notes" value={selectedContact.customer_profile?.notes} />
                                
                                <div className="mt-3">
                                    <dt className="flex items-center text-sm text-slate-500 dark:text-slate-400 mb-1">
                                        <FiTag className="mr-2 h-4 w-4" /> Tags
                                    </dt>
                                    <dd className="flex flex-wrap gap-2">
                                        {(selectedContact.customer_profile?.tags && selectedContact.customer_profile.tags.length > 0) ? (
                                            selectedContact.customer_profile.tags.map(tag => <Badge key={tag} variant="secondary">{tag}</Badge>)
                                        ) : <span className="text-sm text-slate-400">No tags</span>}
                                    </dd>
                                </div>
                            </div>
                        )}
                        {!isFetchingDetail && !selectedContact && (
                            <div className="text-center py-10 text-slate-500 dark:text-slate-400">
                                <FiUserPlus className="mx-auto h-16 w-16 text-slate-300 dark:text-slate-600 mb-4" />
                                <p>Select a contact to view details.</p>
                            </div>
                        )}
                    </CardContent>
                </ScrollArea>
            </Card>

            {/* Edit Contact Modal */}
            {isModalOpen && editingContact && (
                <Dialog open={isModalOpen} onOpenChange={(isOpen) => { if(!isOpen) {setIsModalOpen(false); setEditingContact(null); reset(); setCurrentContactTags([]);} else {setIsModalOpen(true);}}}>
                    <DialogContent className="sm:max-w-[600px] max-h-[90vh] flex flex-col">
                        <DialogHeader>
                            <DialogTitle>{editingContact.id ? 'Edit Contact' : 'Add New Contact'}</DialogTitle>
                            <DialogDescription>
                                {editingContact.id ? `Updating information for ${editingContact.name || editingContact.whatsapp_id}.` : 'Create a new contact.'}
                            </DialogDescription>
                        </DialogHeader>
                        <ScrollArea className="flex-grow pr-2">
                        <form onSubmit={handleSubmit(onSubmit)} className="grid grid-cols-1 md:grid-cols-2 gap-4 p-1">
                            {/* Contact Info Section */}
                            <div className="md:col-span-2 font-semibold text-lg mb-2 border-b pb-1">Contact Info</div>
                            <div>
                                <Label htmlFor="name">Name <span className="text-red-500">*</span></Label>
                                <Input id="name" {...register("name")} className={errors.name ? 'border-red-500' : ''} />
                                {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name.message}</p>}
                            </div>
                            <div>
                                <Label htmlFor="whatsapp_id">WhatsApp ID <span className="text-red-500">*</span></Label>
                                <Input id="whatsapp_id" {...register("whatsapp_id")} readOnly={!!editingContact.id} className={errors.whatsapp_id ? 'border-red-500' : ''}/>
                                {errors.whatsapp_id && <p className="text-xs text-red-500 mt-1">{errors.whatsapp_id.message}</p>}
                            </div>
                            <div>
                                <Label htmlFor="email">Email</Label>
                                <Input id="email" type="email" {...register("email")} className={errors.email ? 'border-red-500' : ''}/>
                                {errors.email && <p className="text-xs text-red-500 mt-1">{errors.email.message}</p>}
                            </div>
                            <div>
                                <Label htmlFor="phone_number">Other Phone</Label>
                                <Input id="phone_number" {...register("phone_number")} className={errors.phone_number ? 'border-red-500' : ''}/>
                                {errors.phone_number && <p className="text-xs text-red-500 mt-1">{errors.phone_number.message}</p>}
                            </div>
                             <div className="md:col-span-2">
                                <Label htmlFor="address">Address</Label>
                                <Input id="address" {...register("address")} className={errors.address ? 'border-red-500' : ''}/>
                                {errors.address && <p className="text-xs text-red-500 mt-1">{errors.address.message}</p>}
                            </div>
                            <div>
                                <Label htmlFor="city">City</Label>
                                <Input id="city" {...register("city")} className={errors.city ? 'border-red-500' : ''}/>
                                {errors.city && <p className="text-xs text-red-500 mt-1">{errors.city.message}</p>}
                            </div>
                            <div>
                                <Label htmlFor="country">Country</Label>
                                <Input id="country" {...register("country")} className={errors.country ? 'border-red-500' : ''}/>
                                {errors.country && <p className="text-xs text-red-500 mt-1">{errors.country.message}</p>}
                            </div>

                             {/* Profile Details Section */}
                            <div className="md:col-span-2 font-semibold text-lg mb-2 mt-4 border-b pb-1">Profile Details</div>
                            <div>
                                <Label htmlFor="date_of_birth">Date of Birth</Label>
                                <Input id="date_of_birth" type="date" {...register("date_of_birth")} className={errors.date_of_birth ? 'border-red-500' : ''}/>
                                {errors.date_of_birth && <p className="text-xs text-red-500 mt-1">{errors.date_of_birth.message}</p>}
                            </div>
                             <div>
                                <Label htmlFor="gender">Gender</Label>
                                <Select onValueChange={(value) => setValue('gender', value)} defaultValue={editingContact?.customer_profile?.gender || ''}>
                                    <SelectTrigger id="gender" className={errors.gender ? 'border-red-500' : ''}> <SelectValue placeholder="Select gender" /> </SelectTrigger>
                                    <SelectContent> <SelectItem value="male">Male</SelectItem> <SelectItem value="female">Female</SelectItem> <SelectItem value="other">Other</SelectItem> <SelectItem value="prefer_not_to_say">Prefer not to say</SelectItem> </SelectContent>
                                </Select>
                                {errors.gender && <p className="text-xs text-red-500 mt-1">{errors.gender.message}</p>}
                            </div>
                            {/* ... other profile fields like occupation, industry, company ... */}
                            <div>
                                <Label htmlFor="occupation">Occupation</Label>
                                <Input id="occupation" {...register("occupation")} />
                            </div>
                             <div>
                                <Label htmlFor="industry">Industry</Label>
                                <Input id="industry" {...register("industry")} />
                            </div>
                             <div className="md:col-span-2">
                                <Label htmlFor="company_name">Company Name</Label>
                                <Input id="company_name" {...register("company_name")} />
                            </div>
                             <div>
                                <Label htmlFor="company_size">Company Size</Label>
                                <Input id="company_size" {...register("company_size")} />
                            </div>
                             <div className="md:col-span-2">
                                <Label htmlFor="company_website">Company Website</Label>
                                <Input id="company_website" type="url" {...register("company_website")} />
                                {errors.company_website && <p className="text-xs text-red-500 mt-1">{errors.company_website.message}</p>}
                            </div>


                            {/* Lead & Preferences Section */}
                            <div className="md:col-span-2 font-semibold text-lg mb-2 mt-4 border-b pb-1">Lead & Preferences</div>
                            <div>
                                <Label htmlFor="lead_status">Lead Status</Label>
                                <Input id="lead_status" {...register("lead_status")} />
                            </div>
                            <div>
                                <Label htmlFor="acquisition_source">Acquisition Source</Label> {/* Updated from lead_source */}
                                <Input id="acquisition_source" {...register("acquisition_source")} />
                            </div>
                            <div>
                                <Label htmlFor="interest_level">Interest Level</Label>
                                <Input id="interest_level" {...register("interest_level")} />
                            </div>
                            <div>
                                <Label htmlFor="preferred_contact_method">Preferred Contact Method</Label>
                                <Input id="preferred_contact_method" {...register("preferred_contact_method")} />
                            </div>
                             <div className="md:col-span-2">
                                <Label htmlFor="communication_frequency">Communication Frequency</Label>
                                <Input id="communication_frequency" {...register("communication_frequency")} />
                            </div>

                            {/* Status & Notes Section */}
                            <div className="md:col-span-2 font-semibold text-lg mb-2 mt-4 border-b pb-1">Status & Notes</div>
                            <div className="flex items-center space-x-2 md:col-span-1">
                                <Checkbox id="is_blocked" {...register("is_blocked")} checked={watchedIsBlocked} onCheckedChange={(checked) => setValue('is_blocked', checked)} />
                                <Label htmlFor="is_blocked" className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                                    Contact Blocked
                                </Label>
                            </div>
                             <div className="flex items-center space-x-2 md:col-span-1">
                                <Checkbox id="needs_human_intervention" {...register("needs_human_intervention")} checked={watchedNeedsIntervention} onCheckedChange={(checked) => setValue('needs_human_intervention', checked)} />
                                <Label htmlFor="needs_human_intervention" className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                                    Needs Human Intervention
                                </Label>
                            </div>
                             <div className="md:col-span-2">
                                <Label htmlFor="notes">Notes</Label>
                                <textarea id="notes" {...register("notes")} rows={3} className="mt-1 block w-full rounded-md border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm dark:bg-slate-700 dark:border-slate-600 dark:text-slate-50" />
                            </div>

                            {/* Tags Section */}
                            <div className="md:col-span-2">
                                <Label htmlFor="tags">Tags</Label>
                                <div className="flex items-center gap-2 mt-1">
                                    <Input
                                        id="newTag"
                                        type="text"
                                        value={newTag}
                                        onChange={(e) => setNewTag(e.target.value)}
                                        placeholder="Add a tag"
                                        className="flex-grow"
                                    />
                                    <Button type="button" variant="outline" onClick={handleAddTag} size="sm">Add Tag</Button>
                                </div>
                                <div className="mt-2 flex flex-wrap gap-2">
                                    {currentContactTags.map(tag => (
                                        <Badge key={tag} variant="secondary" className="flex items-center">
                                            {tag}
                                            <button type="button" onClick={() => handleRemoveTag(tag)} className="ml-2 text-red-500 hover:text-red-700">×</button>
                                        </Badge>
                                    ))}
                                </div>
                            </div>
                        </form>
                        </ScrollArea>
                        <DialogFooter className="mt-auto pt-4 border-t">
                            <DialogClose asChild>
                                <Button type="button" variant="outline" onClick={() => {setIsModalOpen(false); setEditingContact(null); reset(); setCurrentContactTags([]);}}>Cancel</Button>
                            </DialogClose>
                            <Button type="submit" onClick={handleSubmit(onSubmit)} disabled={isSubmitting}>
                                {isSubmitting ? <FiLoader className="animate-spin mr-2" /> : <FiSave className="mr-2" />}
                                Save Changes
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}
        </div>
    );
}