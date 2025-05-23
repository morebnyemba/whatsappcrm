// Filename: src/pages/LoginPage.jsx
import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { Button } from '@/components/ui/button'; // Assuming shadcn/ui
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { toast } from 'sonner';
import { FiLogIn } from 'react-icons/fi';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || "/dashboard"; // Redirect to intended page or dashboard

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    try {
      await auth.login(username, password);
      toast.success("Login successful! Redirecting...");
      navigate(from, { replace: true });
    } catch (err) {
      const errorMessage = err.response?.data?.detail || "Login failed. Please check your credentials.";
      setError(errorMessage);
      toast.error(errorMessage);
      setIsLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-green-400 via-teal-500 to-blue-600 dark:from-gray-800 dark:via-gray-900 dark:to-black p-4">
      <Card className="w-full max-w-md shadow-2xl dark:bg-gray-800">
        <CardHeader className="text-center">
          <div className="inline-block p-3 bg-green-500 dark:bg-green-600 rounded-full mx-auto mb-4">
            <FiLogIn className="h-8 w-8 text-white" />
          </div>
          <CardTitle className="text-3xl font-bold text-gray-800 dark:text-gray-100">Welcome Back!</CardTitle>
          <CardDescription className="text-gray-600 dark:text-gray-400">
            Log in to your WhatsApp CRM dashboard.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            {error && <p className="text-sm text-red-500 dark:text-red-400 bg-red-100 dark:bg-red-900/30 p-3 rounded-md text-center">{error}</p>}
            <div className="space-y-2">
              <Label htmlFor="username" className="text-gray-700 dark:text-gray-300">Username</Label>
              <Input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your username"
                required
                disabled={isLoading}
                className="dark:bg-gray-700 dark:border-gray-600 dark:text-gray-50"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password"className="text-gray-700 dark:text-gray-300">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                required
                disabled={isLoading}
                className="dark:bg-gray-700 dark:border-gray-600 dark:text-gray-50"
              />
            </div>
            <Button type="submit" className="w-full bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600 text-white" disabled={isLoading}>
              {isLoading ? 'Logging in...' : 'Log In'}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="flex flex-col items-center text-xs text-gray-500 dark:text-gray-400 pt-4">
          <p>&copy; {new Date().getFullYear()} AutoWhatsapp CRM</p>
          {/* <Link to="/forgot-password" className="hover:text-green-600 dark:hover:text-green-400">Forgot password?</Link> */}
        </CardFooter>
      </Card>
    </div>
  );
}
