# OCI DevOps Configuration

This folder contains some setup artifacts for using OCI DevOps.  This approach has been deprecated and the recommended solution is using GitHub Actions as described in the main README.md.  

Below find some of the IAM setup for OCI DevOps and build and command spec files are also maintained in this directory for posterity.

1. IAM Setup
    1. Dynamic Group Creation

        1. hm-devops-dg rule with ANY selected (one rule)
        ```
        All {resource.compartment.id = '$ocid_of_hm_compartment', Any {resource.type = 'devopsdeploypipeline', resource.type = 'devopsbuildpipeline', resource.type = 'devopsbuildrun', resource.type = 'devopsdeploystage', resource.type = 'devopsdeployenvironment', resource.type = 'devopsrepository', resource.type = 'devopsconnection', resource.type = 'devopstrigger'}}
        ```
     1. Policy Setup

        1. devops-policy in hm compartment
        ```
        Allow dynamic-group hm-devops-dg to read secret-family in compartment hm
        Allow dynamic-group hm-devops-dg to read secret-family in compartment hm
        Allow dynamic-group hm-devops-dg to manage devops-family in compartment hm
        Allow dynamic-group hm-devops-dg to manage devops-family in compartment hm
        Allow dynamic-group hm-devops-dg to manage virtual-network-family in compartment hm
        Allow dynamic-group hm-devops-dg to manage virtual-network-family in compartment hm
        Allow dynamic-group hm-devops-dg to manage ons-topics in compartment hm
        Allow dynamic-group hm-devops-dg to manage ons-topics in compartment hm
        Allow dynamic-group hm-devops-dg to manage objects in compartment hm
        Allow dynamic-group hm-devops-dg to manage objects in compartment hm
        Allow dynamic-group hm-devops-dg to manage all-artifacts in compartment hm	
        Allow dynamic-group hm-devops-dg to manage all-artifacts in compartment hm
        Allow dynamic-group hm-devops-dg to manage repos in compartment hm	
        Allow dynamic-group hm-devops-dg to manage repos in compartment hm
        Allow dynamic-group hm-devops-dg to manage compute-container-family in compartment hm
        Allow dynamic-group hm-devops-dg to manage compute-container-family in compartment hm
        Allow dynamic-group hm-devops-dg to use compute-container-instances in compartment hm
        ```