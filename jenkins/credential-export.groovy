import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.common.*
import com.cloudbees.plugins.credentials.domains.*
import com.cloudbees.plugins.credentials.impl.*
import com.cloudbees.jenkins.plugins.sshcredentials.impl.*
import org.jenkinsci.plugins.plaincredentials.impl.*



def creds = CredentialsProvider.lookupCredentials(com.cloudbees.plugins.credentials.Credentials.class,Jenkins.instance, null, null);

for (credential in creds) {
    if (credential instanceof UsernamePasswordCredentialsImpl) {
        println credential.getId() + " " + credential.getUsername() + " " + credential.getPassword().getPlainText()
    } else if (credential instanceof StringCredentialsImpl) {
        println credential.getId() + " " + credential.getSecret().getPlainText()
    } else if(credential instanceof BasicSSHUserPrivateKey) {
        println credential.getId() + " " + credential.getUsername() + "\n" + credential.getPrivateKey() + "\n Passphrase: " + credential.getPassphrase()
    } else if (credential.getClass().toString() == "class com.microsoft.azure.util.AzureCredentials") {
        println "AzureCred:" + credential.getSubscriptionId() + " " + credential.getClientId() + " " + credential.getPlainClientSecret() + " " + credential.getTenant()
    } else if (credential.getClass().toString() == "class org.jenkinsci.plugins.github_branch_source.GitHubAppCredentials") {
        println credential.getId() + " " + credential.getUsername() + "\n" + credential.getPrivateKey().getPlainText()
    } else if (credential.getClass().toString() == "class com.cloudbees.jenkins.plugins.awscredentials.AWSCredentialsImpl") {
        println credential.getId() + " " + credential.getAccessKey() + " " + credential.getSecretKey()
    } else if (credential.getClass().toString() == "class com.microsoft.jenkins.keyvault.SecretStringCredentials" || credential.getClass().toString() == "class org.jenkinsci.plugins.azurekeyvaultplugin.credentials.string.AzureSecretStringCredentials") {
    } else {
        println credential.getClass()
    }
}
