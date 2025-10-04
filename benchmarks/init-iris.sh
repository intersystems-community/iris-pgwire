#!/bin/bash
# Initialize IRIS user passwords

iris session IRIS -U %SYS << 'EOF'
// Change _SYSTEM password to reset expiration
set sc = ##class(Security.Users).ChangePassword("_SYSTEM", "SYS", "SYS", 0)
if sc = 1 {
    write "Password reset successfully",!
}

// Disable password expiration for all users
set sc = ##class(Security.Users).UnExpireUserPasswords("*")
write "Password expiration disabled",!
halt
EOF
