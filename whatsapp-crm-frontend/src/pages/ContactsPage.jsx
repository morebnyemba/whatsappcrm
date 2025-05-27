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
// DropdownMenu components are imported but not explicitly used in the last provided snippet, uncomment if needed
// import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuCheckboxItem, DropdownMenuLabel, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
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

// Updated Zod schema to reflect CustomerProfile model structure
const contactFormSchema = z.object({
    name: z.string().min(1, "Display Name (from Contact model) is required").max(255),
    whatsapp_id: z.string().min(1, "WhatsApp ID is required").max(50),
    
    first_name: z.string().max(100).or(z.literal('')).nullable(),
    last_name: z.string().max(100).or(z.literal('')).nullable(),
    email: z.string().email("Invalid email address").or(z.literal('')).nullable(),
    secondary_phone_number: z.string().max(30).or(z.literal('')).nullable(),
    ecocash_number: z.string().max(50).or(z.literal('')).nullable(),
    date_of_birth: z.string().nullable().refine(val => val === null || val === '' || !isNaN(Date.parse(val)) || /^\d{4}-\d{2}-\d{2}$/.test(val), { message: "Invalid date" }),
    gender: z.string().max(20).or(z.literal('')).nullable(),
    
    company_name: z.string().max(255).or(z.literal('')).nullable(),
    job_title: z.string().max(255).or(z.literal('')).nullable(),

    address_line_1: z.string().max(255).or(z.literal('')).nullable(),
    address_line_2: z.string().max(255).or(z.literal('')).nullable(),
    city: z.string().max(100).or(z.literal('')).nullable(),
    state_province: z.string().max(100).or(z.literal('')).nullable(),
    postal_code: z.string().max(20).or(z.literal('')).nullable(),
    country: z.string().max(100).or(z.literal('')).nullable(),

    lifecycle_stage: z.string().max(50).or(z.literal('')).nullable(),
    acquisition_source: z.string().max(150).or(z.literal('')).nullable(),
    notes: z.string().or(z.literal('')).nullable(),
    
    is_blocked: z.boolean().default(false),
    needs_human_intervention: z.boolean().default(false),
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
    } else if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) {
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
                            <TableHead key={column.id || column.accessorKey} className="whitespace-nowrap">
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
                                let cellValue;
                                if (column.accessorKey) {
                                    cellValue = column.accessorKey.split('.').reduce((acc, part) => acc && acc[part], row);
                                } else if (column.accessorFn) {
                                    cellValue = column.accessorFn(row);
                                }

                                if (column.cell) {
                                    cellValue = column.cell({ row, getValue: () => cellValue });
                                } else if (column.id === 'is_blocked' || column.id === 'needs_human_intervention') {
                                    cellValue = cellValue ? <Badge variant="destructive">Yes</Badge> : <Badge variant="outline">No</Badge>;
                                } else if (column.id === 'tags') {
                                     // This relies on ContactSerializer providing customer_profile.tags or a similar structure.
                                     // Currently, ContactSerializer does not. This will show N/A.
                                     cellValue = Array.isArray(row.customer_profile?.tags) && row.customer_profile.tags.length > 0 
                                        ? row.customer_profile.tags.join(', ') 
                                        : 'N/A';
                                } else if (column.id === 'last_seen' && cellValue) {
                                    const parsedDate = parseISO(cellValue);
                                    cellValue = isValid(parsedDate) ? format(parsedDate, "PPpp") : "Invalid Date";
                                } else if (cellValue === null || cellValue === undefined || cellValue === '') {
                                    cellValue = "N/A";
                                }
                                return <TableCell key={column.id || column.accessorKey} className="whitespace-nowrap">{cellValue}</TableCell>;
                            })}
                            <TableCell className="whitespace-nowrap">
                                <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); onRowClick(row.id); }}>
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

    const [newTag, setNewTag] = useState('');
    const [currentContactTags, setCurrentContactTags] = useState([]);

    const { register, handleSubmit, reset, formState: { errors }, setValue, watch } = useForm({
        resolver: zodResolver(contactFormSchema),
        defaultValues: {
            name: '', 
            whatsapp_id: '',
            is_blocked: false,
            needs_human_intervention: false,
            first_name: '',
            last_name: '',
            email: '',
            secondary_phone_number: '',
            ecocash_number: '',
            date_of_birth: null,
            gender: '',
            company_name: '',
            job_title: '',
            address_line_1: '',
            address_line_2: '',
            city: '',
            state_province: '',
            postal_code: '',
            country: '',
            lifecycle_stage: '',
            acquisition_source: '',
            notes: '',
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
            console.error("Failed to fetch contacts list:", error);
            // toast is handled by apiCall
        } finally {
            setIsLoading(false);
        }
    }, [pagination.pageSize]);

    useEffect(() => {
        fetchContacts(pagination.pageIndex + 1, searchTerm);
    }, [fetchContacts, pagination.pageIndex, searchTerm]);

    const handleSelectContact = async (contactId) => {
        if (selectedContact?.id === contactId && !isModalOpen) { 
            setSelectedContact(null);
            return;
        }
        setIsFetchingDetail(true);
        setSelectedContact(null); 
        try {
            const data = await apiCall(`/crm-api/conversations/contacts/${contactId}/`); 
            setSelectedContact(data);
        } catch (error) {
            toast.error("Failed to fetch contact details.");
            console.error("Fetch contact detail error:", error.data || error.message);
        } finally {
            setIsFetchingDetail(false);
        }
    };
    
    const handleOpenEditModal = (contactDataToEdit) => { 
        setEditingContact(contactDataToEdit);
        const profile = contactDataToEdit.customer_profile || {};
        reset({
            name: contactDataToEdit.name || '',
            whatsapp_id: contactDataToEdit.whatsapp_id || '',
            is_blocked: contactDataToEdit.is_blocked || false,
            needs_human_intervention: contactDataToEdit.needs_human_intervention || false,
            first_name: profile.first_name || '',
            last_name: profile.last_name || '',
            email: profile.email || '',
            secondary_phone_number: profile.secondary_phone_number || '',
            ecocash_number: profile.ecocash_number || '',
            date_of_birth: profile.date_of_birth ? format(parseISO(profile.date_of_birth), 'yyyy-MM-dd') : '',
            gender: profile.gender || '',
            company_name: profile.company_name || '',
            job_title: profile.job_title || '',
            address_line_1: profile.address_line_1 || '',
            address_line_2: profile.address_line_2 || '',
            city: profile.city || '',
            state_province: profile.state_province || '',
            postal_code: profile.postal_code || '',
            country: profile.country || '',
            lifecycle_stage: profile.lifecycle_stage || '',
            acquisition_source: profile.acquisition_source || '',
            notes: profile.notes || '',
        });
        setCurrentContactTags(profile.tags || []); 
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
        Object.keys(contactPayload).forEach(key => contactPayload[key] === undefined && delete contactPayload[key]);

        const profilePayload = {
            first_name: formData.first_name,
            last_name: formData.last_name,
            email: formData.email,
            secondary_phone_number: formData.secondary_phone_number,
            ecocash_number: formData.ecocash_number,
            date_of_birth: formData.date_of_birth || null,
            gender: formData.gender,
            company_name: formData.company_name,
            job_title: formData.job_title,
            address_line_1: formData.address_line_1,
            address_line_2: formData.address_line_2,
            city: formData.city,
            state_province: formData.state_province,
            postal_code: formData.postal_code,
            country: formData.country,
            lifecycle_stage: formData.lifecycle_stage,
            acquisition_source: formData.acquisition_source,
            notes: formData.notes,
            tags: currentContactTags, 
        };
        Object.keys(profilePayload).forEach(key => profilePayload[key] === undefined && delete profilePayload[key]);
        
        try {
            if (Object.keys(contactPayload).length > 0) {
                 await apiCall(`/crm-api/conversations/contacts/${editingContact.id}/`, 'PATCH', contactPayload);
            }
            if (Object.keys(profilePayload).length > 0 && editingContact.id) {
                await apiCall(`/crm-api/customer-data/profiles/${editingContact.id}/`, 'PATCH', profilePayload);
            }
            toast.success("Contact updated successfully!");
            setIsModalOpen(false);
            setEditingContact(null);
            fetchContacts(pagination.pageIndex + 1, searchTerm); 
            if (selectedContact?.id === editingContact.id) { 
                handleSelectContact(editingContact.id);
            }
        } catch (error) {
            console.error("Submit error:", error.data || error.message);
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
    
    // Helper to get full name for display
    const getContactDisplayName = (contact) => {
        if (!contact) return "N/A";
        const profile = contact.customer_profile;
        if (profile?.first_name && profile?.last_name) {
            return `${profile.first_name} ${profile.last_name}`;
        }
        if (profile?.first_name) return profile.first_name;
        if (profile?.last_name) return profile.last_name;
        return contact.name || contact.whatsapp_id; // Fallback to Contact.name then whatsapp_id
    };


    const columns = useMemo(() => [
        { 
            header: 'Name', 
            id: 'displayName', // Use id for columns not directly mapping to a single accessorKey
            accessorFn: row => getContactDisplayName(row) // Use the helper for display name
        },
        { header: 'WhatsApp ID', accessorKey: 'whatsapp_id', id: 'whatsapp_id' },
        { header: 'Blocked', accessorKey: 'is_blocked', id: 'is_blocked' },
        { header: 'Needs Attention', accessorKey: 'needs_human_intervention', id: 'needs_human_intervention' },
        { 
            header: 'Tags', 
            id: 'tags',
            // This accessor expects `customer_profile` to be on the `row` object.
            // For the list view, `row` comes from `ContactSerializer` which won't have `customer_profile`.
            // This will only work if `ContactSerializer` is updated to include profile tags.
            accessorFn: row => row.customer_profile?.tags || [] 
        },
        { header: 'Last Seen', accessorKey: 'last_seen', id: 'last_seen' },
    ], []);

    return (
        <div className="flex h-[calc(100vh-var(--header-height,4rem)-2rem)] gap-6 p-1">
            {/* Main Contacts List */}
            <Card className="w-2/3 flex flex-col">
                <CardHeader>
                    <div className="flex justify-between items-center">
                        <div><CardTitle>Contacts</CardTitle><CardDescription>Manage your customer contacts.</CardDescription></div>
                    </div>
                    <div className="mt-4 relative">
                        <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                        <Input type="search" placeholder="Search contacts..." className="pl-9" value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)}/>
                    </div>
                </CardHeader>
                <CardContent className="flex-grow overflow-hidden">
                     <ScrollArea className="h-full">
                        <DataTable columns={columns} data={contacts} isLoading={isLoading} onRowClick={handleSelectContact} selectedRowId={selectedContact?.id} />
                    </ScrollArea>
                </CardContent>
                <div className="p-4 border-t flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
                    <div>Page {pagination.pageIndex + 1} of {pageCount || 1}</div>
                    <div className="space-x-2">
                        <Button variant="outline" size="sm" onClick={() => setPagination(prev => ({ ...prev, pageIndex: Math.max(0, prev.pageIndex - 1) }))} disabled={pagination.pageIndex === 0 || isLoading}>Previous</Button>
                        <Button variant="outline" size="sm" onClick={() => setPagination(prev => ({ ...prev, pageIndex: Math.min(pageCount - 1, prev.pageIndex + 1) }))} disabled={pagination.pageIndex >= pageCount - 1 || isLoading}>Next</Button>
                    </div>
                </div>
            </Card>

            {/* Contact Detail Panel */}
            <Card className="w-1/3 flex flex-col">
                <CardHeader className="flex flex-row justify-between items-center">
                    <div><CardTitle>Contact Details</CardTitle><CardDescription>View and edit contact information.</CardDescription></div>
                    {selectedContact && (
                         <TooltipProvider><Tooltip><TooltipTrigger asChild>
                                    <Button variant="outline" size="icon" onClick={() => handleOpenEditModal(selectedContact)} disabled={isFetchingDetail}><FiEdit3 className="h-4 w-4" /></Button>
                         </TooltipTrigger><TooltipContent><p>Edit Contact</p></TooltipContent></Tooltip></TooltipProvider>
                    )}
                </CardHeader>
                <ScrollArea className="flex-grow">
                    <CardContent className="p-6">
                        {isFetchingDetail && ( <div className="space-y-3"> <Skeleton className="h-8 w-3/4" /> <Skeleton className="h-4 w-1/2" /> <Skeleton className="h-4 w-1/3" /> <hr className="my-4"/> <Skeleton className="h-6 w-1/4 mb-2" /> <Skeleton className="h-4 w-full" /> <Skeleton className="h-4 w-full" /> <Skeleton className="h-4 w-3/4" /> </div> )}
                        {!isFetchingDetail && selectedContact && (
                            <div>
                                <div className="flex items-center mb-6">
                                    <Avatar className="h-16 w-16 mr-4">
                                        <AvatarImage src={`https://ui-avatars.com/api/?name=${encodeURIComponent(getContactDisplayName(selectedContact))}&background=random`} />
                                        <AvatarFallback>{(getContactDisplayName(selectedContact) || 'U').substring(0, 2).toUpperCase()}</AvatarFallback>
                                    </Avatar>
                                    <div>
                                        <h2 className="text-xl font-semibold">{getContactDisplayName(selectedContact)}</h2>
                                        <p className="text-sm text-slate-500 dark:text-slate-400">{selectedContact.whatsapp_id}</p>
                                    </div>
                                </div>
                                <h3 className="text-md font-semibold mb-2 text-slate-700 dark:text-slate-200 border-b pb-1">Personal Info</h3>
                                <ProfileFieldDisplay icon={FiMail} label="Email" value={selectedContact.customer_profile?.email} />
                                <ProfileFieldDisplay icon={FiPhone} label="Secondary Phone" value={selectedContact.customer_profile?.secondary_phone_number} />
                                <ProfileFieldDisplay icon={FiPhone} label="Ecocash Number" value={selectedContact.customer_profile?.ecocash_number} />
                                <ProfileFieldDisplay icon={FiCalendar} label="Date of Birth" value={selectedContact.customer_profile?.date_of_birth} type="date" />
                                <ProfileFieldDisplay icon={FiUsers} label="Gender" value={selectedContact.customer_profile?.gender} />
                                
                                <h3 className="text-md font-semibold mt-4 mb-2 text-slate-700 dark:text-slate-200 border-b pb-1">Location</h3>
                                <ProfileFieldDisplay icon={FiMapPin} label="Address Line 1" value={selectedContact.customer_profile?.address_line_1} />
                                <ProfileFieldDisplay icon={FiMapPin} label="Address Line 2" value={selectedContact.customer_profile?.address_line_2} />
                                <ProfileFieldDisplay icon={FiMapPin} label="City" value={selectedContact.customer_profile?.city} />
                                <ProfileFieldDisplay icon={FiMapPin} label="State/Province" value={selectedContact.customer_profile?.state_province} />
                                <ProfileFieldDisplay icon={FiMapPin} label="Postal Code" value={selectedContact.customer_profile?.postal_code} />
                                <ProfileFieldDisplay icon={FiMapPin} label="Country" value={selectedContact.customer_profile?.country} />
                                
                                <h3 className="text-md font-semibold mt-4 mb-2 text-slate-700 dark:text-slate-200 border-b pb-1">Professional Details</h3>
                                <ProfileFieldDisplay icon={FiBriefcase} label="Company" value={selectedContact.customer_profile?.company_name} />
                                <ProfileFieldDisplay icon={FiBriefcase} label="Job Title" value={selectedContact.customer_profile?.job_title} />
                                
                                <h3 className="text-md font-semibold mt-4 mb-2 text-slate-700 dark:text-slate-200 border-b pb-1">CRM Data</h3>
                                <ProfileFieldDisplay icon={FiTrendingUp} label="Lifecycle Stage" value={selectedContact.customer_profile?.lifecycle_stage} />
                                <ProfileFieldDisplay icon={FiInfo} label="Acquisition Source" value={selectedContact.customer_profile?.acquisition_source} />
                                
                                <div className="mt-3">
                                    <dt className="flex items-center text-sm text-slate-500 dark:text-slate-400 mb-1"> <FiTag className="mr-2 h-4 w-4" /> Tags </dt>
                                    <dd className="flex flex-wrap gap-2">
                                        {(selectedContact.customer_profile?.tags && selectedContact.customer_profile.tags.length > 0) ? (
                                            selectedContact.customer_profile.tags.map(tag => <Badge key={tag} variant="secondary">{tag}</Badge>)
                                        ) : <span className="text-sm text-slate-400">No tags</span>}
                                    </dd>
                                </div>
                                <h3 className="text-md font-semibold mt-4 mb-2 text-slate-700 dark:text-slate-200 border-b pb-1">Status & Notes</h3>
                                <ProfileFieldDisplay icon={FiToggleLeft} label="Blocked" value={selectedContact.is_blocked} type="boolean" />
                                <ProfileFieldDisplay icon={FiAlertCircle} label="Needs Human Intervention" value={selectedContact.needs_human_intervention} type="boolean" />
                                <ProfileFieldDisplay icon={FiEdit} label="Notes" value={selectedContact.customer_profile?.notes} />
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
                                {editingContact.id ? `Updating information for ${getContactDisplayName(editingContact)}.` : 'Create a new contact.'}
                            </DialogDescription>
                        </DialogHeader>
                        <ScrollArea className="flex-grow pr-2">
                        <form onSubmit={handleSubmit(onSubmit)} className="grid grid-cols-1 md:grid-cols-2 gap-4 p-1">
                            <div className="md:col-span-2 font-semibold text-lg mb-2 border-b pb-1">Core Contact Info</div>
                            <div>
                                <Label htmlFor="name">Display Name (WhatsApp)</Label>
                                <Input id="name" {...register("name")} />
                                {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name.message}</p>}
                            </div>
                            <div>
                                <Label htmlFor="whatsapp_id">WhatsApp ID</Label>
                                <Input id="whatsapp_id" {...register("whatsapp_id")} readOnly={!!editingContact.id}/>
                                {errors.whatsapp_id && <p className="text-xs text-red-500 mt-1">{errors.whatsapp_id.message}</p>}
                            </div>
                            
                            <div className="md:col-span-2 font-semibold text-lg mb-2 mt-4 border-b pb-1">Personal Details (Profile)</div>
                            <div><Label htmlFor="first_name">First Name</Label><Input id="first_name" {...register("first_name")} /></div>
                            <div><Label htmlFor="last_name">Last Name</Label><Input id="last_name" {...register("last_name")} /></div>
                            <div><Label htmlFor="email">Email</Label><Input id="email" type="email" {...register("email")} />{errors.email && <p className="text-xs text-red-500 mt-1">{errors.email.message}</p>}</div>
                            <div><Label htmlFor="secondary_phone_number">Secondary Phone</Label><Input id="secondary_phone_number" {...register("secondary_phone_number")} /></div>
                            <div><Label htmlFor="ecocash_number">Ecocash Number</Label><Input id="ecocash_number" {...register("ecocash_number")} /></div>
                            <div><Label htmlFor="date_of_birth">Date of Birth</Label><Input id="date_of_birth" type="date" {...register("date_of_birth")} />{errors.date_of_birth && <p className="text-xs text-red-500 mt-1">{errors.date_of_birth.message}</p>}</div>
                            <div> <Label htmlFor="gender">Gender</Label> <Select onValueChange={(value) => setValue('gender', value)} defaultValue={editingContact?.customer_profile?.gender || ''}> <SelectTrigger id="gender"> <SelectValue placeholder="Select gender" /> </SelectTrigger> <SelectContent> <SelectItem value="male">Male</SelectItem> <SelectItem value="female">Female</SelectItem> <SelectItem value="other">Other</SelectItem> <SelectItem value="prefer_not_to_say">Prefer not to say</SelectItem> </SelectContent> </Select> </div>

                            <div className="md:col-span-2 font-semibold text-lg mb-2 mt-4 border-b pb-1">Location Details (Profile)</div>
                            <div><Label htmlFor="address_line_1">Address Line 1</Label><Input id="address_line_1" {...register("address_line_1")} /></div>
                            <div><Label htmlFor="address_line_2">Address Line 2</Label><Input id="address_line_2" {...register("address_line_2")} /></div>
                            <div><Label htmlFor="city">City</Label><Input id="city" {...register("city")} /></div>
                            <div><Label htmlFor="state_province">State/Province</Label><Input id="state_province" {...register("state_province")} /></div>
                            <div><Label htmlFor="postal_code">Postal Code</Label><Input id="postal_code" {...register("postal_code")} /></div>
                            <div><Label htmlFor="country">Country</Label><Input id="country" {...register("country")} /></div>

                            <div className="md:col-span-2 font-semibold text-lg mb-2 mt-4 border-b pb-1">Professional Details (Profile)</div>
                            <div><Label htmlFor="company_name">Company Name</Label><Input id="company_name" {...register("company_name")} /></div>
                            <div><Label htmlFor="job_title">Job Title</Label><Input id="job_title" {...register("job_title")} /></div>
                            
                            <div className="md:col-span-2 font-semibold text-lg mb-2 mt-4 border-b pb-1">CRM Data (Profile)</div>
                            <div> <Label htmlFor="lifecycle_stage">Lifecycle Stage</Label> <Select onValueChange={(value) => setValue('lifecycle_stage', value)} defaultValue={editingContact?.customer_profile?.lifecycle_stage || 'lead'}> <SelectTrigger id="lifecycle_stage"> <SelectValue placeholder="Select stage" /> </SelectTrigger> <SelectContent> <SelectItem value="lead">Lead</SelectItem> <SelectItem value="opportunity">Opportunity</SelectItem> <SelectItem value="customer">Customer</SelectItem> <SelectItem value="vip">VIP Customer</SelectItem> <SelectItem value="churned">Churned</SelectItem><SelectItem value="other">Other</SelectItem> </SelectContent> </Select> </div>
                            <div><Label htmlFor="acquisition_source">Acquisition Source</Label><Input id="acquisition_source" {...register("acquisition_source")} /></div>
                            <div className="md:col-span-2"><Label htmlFor="notes">Notes</Label><textarea id="notes" {...register("notes")} rows={3} className="mt-1 block w-full rounded-md border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm dark:bg-slate-700 dark:border-slate-600 dark:text-slate-50" /></div>
                            <div className="md:col-span-2"> <Label htmlFor="tags">Tags</Label> <div className="flex items-center gap-2 mt-1"> <Input id="newTag" type="text" value={newTag} onChange={(e) => setNewTag(e.target.value)} placeholder="Add a tag" className="flex-grow"/> <Button type="button" variant="outline" onClick={handleAddTag} size="sm">Add Tag</Button> </div> <div className="mt-2 flex flex-wrap gap-2"> {currentContactTags.map(tag => ( <Badge key={tag} variant="secondary" className="flex items-center"> {tag} <button type="button" onClick={() => handleRemoveTag(tag)} className="ml-2 text-red-500 hover:text-red-700">×</button> </Badge> ))} </div> </div>

                            <div className="md:col-span-2 font-semibold text-lg mb-2 mt-4 border-b pb-1">Status (Contact)</div>
                            <div className="flex items-center space-x-2 md:col-span-1"><Checkbox id="is_blocked" {...register("is_blocked")} checked={watchedIsBlocked} onCheckedChange={(checked) => setValue('is_blocked', checked)} /><Label htmlFor="is_blocked">Contact Blocked</Label></div>
                            <div className="flex items-center space-x-2 md:col-span-1"><Checkbox id="needs_human_intervention" {...register("needs_human_intervention")} checked={watchedNeedsIntervention} onCheckedChange={(checked) => setValue('needs_human_intervention', checked)} /><Label htmlFor="needs_human_intervention">Needs Human Intervention</Label></div>
                        </form>
                        </ScrollArea>
                        <DialogFooter className="mt-auto pt-4 border-t">
                            <DialogClose asChild><Button type="button" variant="outline" onClick={() => {setIsModalOpen(false); setEditingContact(null); reset(); setCurrentContactTags([]);}}>Cancel</Button></DialogClose>
                            <Button type="submit" onClick={handleSubmit(onSubmit)} disabled={isSubmitting}>{isSubmitting ? <FiLoader className="animate-spin mr-2" /> : <FiSave className="mr-2" />}Save Changes</Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            )}
        </div>
    );
}