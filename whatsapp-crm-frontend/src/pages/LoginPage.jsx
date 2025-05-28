// Filename: src/pages/LoginPage.jsx
import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { toast } from 'sonner';
import { FiLogIn, FiLock, FiUser } from 'react-icons/fi';
import { motion } from 'framer-motion';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || "/dashboard";

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Validate inputs before submitting
    if (!username.trim() || !password.trim()) {
      toast.error("Please fill in all fields");
      return;
    }
    
    setIsLoading(true);
    setError('');
    
    try {
      await auth.login(username, password);
      toast.success("Login successful!", {
        description: "You're being redirected to your dashboard",
        duration: 2000,
      });
      setTimeout(() => navigate(from, { replace: true }), 1500);
    } catch (err) {
      const errorMessage = err.response?.data?.detail || "Login failed. Please check your credentials.";
      setError(errorMessage);
      toast.error("Login Failed", {
        description: errorMessage,
        action: {
          label: "Retry",
          onClick: () => {
            setUsername('');
            setPassword('');
          },
        },
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-green-500 via-teal-600 to-blue-700 dark:from-gray-800 dark:via-gray-900 dark:to-black p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-md"
      >
        <Card className="w-full shadow-2xl dark:bg-gray-800/95 backdrop-blur-sm border border-gray-200/20">
          <CardHeader className="text-center space-y-4">
            <motion.div 
              initial={{ scale: 0.9 }}
              animate={{ scale: 1 }}
              transition={{ type: "spring", stiffness: 200 }}
              className="inline-block p-4 bg-gradient-to-r from-green-500 to-teal-500 rounded-xl mx-auto"
            >
              <FiLogIn className="h-10 w-10 text-white" />
            </motion.div>
            <div>
              <CardTitle className="text-3xl font-bold text-gray-800 dark:text-gray-100">
                Welcome to Your AutoWhatsApp Instance
              </CardTitle>
              <CardDescription className="text-gray-600 dark:text-gray-300 mt-2 text-sm leading-relaxed">
                We appreciate your business. This is the frontend of your instance. 
                Please login with the details provided from Slyker Tech Web Services.
              </CardDescription>
            </div>
          </CardHeader>
          
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              {error && (
                <motion.p 
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="text-sm text-red-500 dark:text-red-400 bg-red-100 dark:bg-red-900/30 p-3 rounded-md text-center"
                >
                  {error}
                </motion.p>
              )}
              
              <div className="space-y-3">
                <Label htmlFor="username" className="text-gray-700 dark:text-gray-300 flex items-center gap-2">
                  <FiUser className="h-4 w-4" />
                  Username
                </Label>
                <Input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Enter your username"
                  required
                  disabled={isLoading}
                  className="dark:bg-gray-700/50 dark:border-gray-600 dark:text-gray-50 h-11"
                />
              </div>
              
              <div className="space-y-3">
                <Label htmlFor="password" className="text-gray-700 dark:text-gray-300 flex items-center gap-2">
                  <FiLock className="h-4 w-4" />
                  Password
                </Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  required
                  disabled={isLoading}
                  className="dark:bg-gray-700/50 dark:border-gray-600 dark:text-gray-50 h-11"
                />
              </div>
              
              <motion.div whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.98 }}>
                <Button 
                  type="submit" 
                  className="w-full bg-gradient-to-r from-green-600 to-teal-600 hover:from-green-700 hover:to-teal-700 dark:from-green-600 dark:to-teal-600 dark:hover:from-green-700 dark:hover:to-teal-700 text-white h-11 font-medium shadow-lg"
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <span className="flex items-center gap-2">
                      <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Logging in...
                    </span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <FiLogIn className="h-4 w-4" />
                      Log In
                    </span>
                  )}
                </Button>
              </motion.div>
            </form>
          </CardContent>
          
          <CardFooter className="flex flex-col items-center text-xs text-gray-500 dark:text-gray-400 pt-4 border-t border-gray-200/20">
            <p className="text-center">
              &copy; {new Date().getFullYear()} AutoWhatsApp CRM<br />
              Powered by Slyker Tech Web Services
            </p>
          </CardFooter>
        </Card>
      </motion.div>
    </div>
  );
}